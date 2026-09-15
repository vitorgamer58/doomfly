"""Shared, read-only live broadcast. The local process owns the neural/game loop.

Only GET /state and /health are exposed. No filesystem, shell, credentials,
remote controls, or model-mutating endpoint. Stale frames never become replays.
"""
import argparse,base64,hashlib,io,json,threading,time,uuid,logging
import re,signal
from logging.handlers import RotatingFileHandler
from collections import deque
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import numpy as np
from PIL import Image
from doom.native import NativeBrain,BUILD
from doom.engine import NeuralControls
from doom.game import Game,retinal_samples
from doom.reward import SugarReinforcement
from doom.provenance import provenance
from doom.broadcast import Broadcast,DISPLAY_FPS
from doom.checkpoint import Checkpoints
from doom.archive import AuditArchive
from doom.observer import NativeObserver,ObserverUnavailable,ObserverBusy,camera_query
from doom.monitor import ActivityMonitor,activity_groups
from doom.life_metrics import LifeMetrics
from doom.death_snapshots import DeathSnapshots
ROOT=Path(__file__).resolve().parents[1]
NOCICEPTIVE_INPUTS=['snxx29','random-matched','random-dose-matched'];RANDOM_INPUTS=['random-matched','random-dose-matched']
latest={'status':'starting','generated_at_ms':0}; stop=threading.Event()
broadcast=Broadcast()
observer=None

def encoded_frame(rgb):
    f=io.BytesIO();Image.fromarray(rgb).save(f,format='JPEG',quality=75)
    return 'data:image/jpeg;base64,'+base64.b64encode(f.getvalue()).decode()

def git_state():
    import subprocess
    def git(*command):
        try:return subprocess.run(['git',*command],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
        except Exception:return None
    return {'fork_commit':git('rev-parse','HEAD'),'upstream_base_commit':git('merge-base','HEAD','main'),
            'uncommitted_source_changes':git('status','--porcelain','--','doom','doom_learning','doom_learning_v6')}

def run_loop(args):
    global latest,observer
    try:
        manifest=json.loads((ROOT/'outputs/doom/malecns_v1/manifest.json').read_text())
        training=None;transducer=None
        if args.model=='experimental-v6':
            from doom_learning_v6.calibration import calibrated_brain
            from doom.training import DamageTraining,candidate_provenance
            brain=calibrated_brain()
            if args.damage_input in NOCICEPTIVE_INPUTS:
                from doom.nociception import NociceptiveTransducer,load_population,load_dose_calibration
                population=load_population(args.damage_input,brain.ids,seed=args.nociception_seed,modulation_mask=brain.modulation_mask)
                calibration=None;gain=args.nociception_gain
                if args.damage_input=='random-dose-matched':
                    calibration=load_dose_calibration(args.nociception_dose_calibration,seed=args.nociception_seed,
                        pulse_ms=args.nociception_pulse_ms,decay_ms=args.nociception_decay_ms)
                    gain=calibration['random_dose_matched_gain_mv']
                transducer=NociceptiveTransducer(population,gain=gain,pulse_ms=args.nociception_pulse_ms,
                    decay_ms=args.nociception_decay_ms,damage_reference=args.nociception_damage_reference,
                    left_right_mode=args.nociception_left_right_mode,dt_ms=brain.dt,calibration=calibration)
            training=DamageTraining(brain,args.learning,damage_input=args.damage_input,nociception=transducer)
            for r in brain.circuit['report']['DAN']+brain.circuit['report']['MBON']:
                manifest['readouts'].append({k:r[k] for k in ['index','id','type']}|{'side':r['soma_side']})
            if transducer:
                # Recording readouts only; the decoder selects DNp20/DNpe017 by type.
                for r in transducer.report['neurons']:
                    manifest['readouts'].append({'index':r['index'],'id':r['body_id'],'type':r['type'],'side':r['side']})
            manifest['training']='Experimental v6 plasticity on 4,184 existing KC-to-MBON11 edges; associative learning and survival improvement unvalidated.'
            manifest['visual_dynamics']='R1–R6 luminance and 811 R8 RGB proxies, filtered in <=10 ms bins; inferred projection, simplified spiking physiology; unvalidated.'
            manifest['additional_R8_inputs']=len(brain.r8)
        else:brain=NativeBrain(ROOT/'outputs/doom/malecns_v1/graph.npz')
        phase=('training' if args.learning else 'frozen-control') if training else 'baseline'
        controls=NeuralControls(manifest['readouts'],mode=args.decoder);game=Game(seed=args.seed,scenario=args.scenario,spectator=True)
        origin=provenance(ROOT/'outputs/doom/malecns_v1/graph.npz',BUILD,game.assets)
        if training:
            origin['candidate']=candidate_provenance(brain,ROOT,training)
            origin['model_revision']='adaptive-centered-v6-live-v1'
            origin['kernel']=brain.build
        reward=SugarReinforcement(args.reward=='sugar')
        if args.condition=='retina_disconnected':
            for i in brain.retina:brain.weight[brain.ptr[i]:brain.ptr[i+1]]=0
        if args.condition=='all_edges_disconnected':brain.weight.fill(0)
        identity={'provenance':origin,'seed':args.seed,'decoder':args.decoder,'condition':args.condition,'reward':args.reward,'phase':phase}
        # Upstream identity is unchanged so existing PPL101 checkpoints still resume.
        if training and args.damage_input!='ppl101':identity['damage_input']=args.damage_input
        CheckpointClass=Checkpoints
        if training:
            from doom.training_checkpoint import TrainingCheckpoints
            CheckpointClass=TrainingCheckpoints
        checkpoints=CheckpointClass(args.checkpoint_dir,identity) if args.checkpoint_dir else None
        recovered=checkpoints.restore(brain,controls,game) if checkpoints and args.resume else None
        try:observer=NativeObserver(game,args.seed,args.scenario)
        except Exception:
            logging.getLogger('doom-observer').exception('Native spectator unavailable; primary continues')
        run_id=str(uuid.uuid4());start=time.monotonic();tick=recovered['tick'] if recovered else 0;seq=0;last_publish=0
        neural_start=brain.sim_ms/1000;study_id=recovered.get('study_id') if recovered else run_id
        if recovered:reward.__dict__.update(recovered['reward'])
        if recovered and training:
            training.restore(recovered['training']);training.new_round()
        total_actions=recovered['total_actions'] if recovered else 0;history=deque(maxlen=160);timeline=deque(maxlen=50);episodes=deque(recovered.get('episodes',[]) if recovered else [],maxlen=12)
        group_names=np.unique(brain.superclass);groups=[np.flatnonzero(brain.superclass==k) for k in group_names]
        # Fixed display sample: ascending graph indices in visual system, central
        # brain and descending population. Raster points are recorded spikes.
        import pyarrow.feather as feather
        nodes=feather.read_table(ROOT/'connectome_data/malecns_v1/normalized/neurons.feather').to_pandas()
        annotations=feather.read_table(ROOT/'connectome_data/malecns_v1/annotations.feather').to_pandas().set_index('bodyId')
        retina_sides=annotations.loc[brain.ids[brain.retina],'rootSide'].to_numpy()
        monitor=ActivityMonitor(activity_groups(annotations.loc[brain.ids],transducer.indices if transducer else None),brain.ids)
        display=[]
        for superclass in ['ol_intrinsic','visual_projection','cb_intrinsic','descending_neuron']:
            inds=np.flatnonzero(nodes.superclass.eq(superclass).to_numpy())
            display.extend(inds[np.linspace(0,len(inds)-1,min(32,len(inds)),dtype=int)].tolist())
        if training:display[-4:]=list(brain.circuit['dan'])+list(brain.circuit['mb'])
        display=np.asarray(display);window_counts=np.zeros(brain.n,dtype=np.int32);window_ms=0
        audit_dir=Path(args.audit_dir);audit_dir.mkdir(parents=True,exist_ok=True)
        audit_path=audit_dir/'audit.jsonl'
        audit_handler=RotatingFileHandler(audit_path,maxBytes=20_000_000,backupCount=4)
        archive=AuditArchive(audit_dir/'archive',run_id)
        audit_logger=logging.getLogger('doom-audit');audit_logger.handlers=[audit_handler,archive];audit_logger.setLevel(logging.INFO);audit_logger.propagate=False
        lives=LifeMetrics(audit_dir/'lives.jsonl');lives.start(game.observation(),brain.sim_ms)
        snapshots=DeathSnapshots(audit_dir/'death-snapshots.jsonl',full_dir=audit_dir/'death-voltages' if args.death_snapshot_full else None)
        previous_light=None
        run_record={'run_id':run_id,'study_id':study_id,'phase':phase,'started_at_ms':int(time.time()*1000),
            'damage_input':args.damage_input if training else None,'monitor':monitor.report(),
            'logs':{'lives':'lives.jsonl','death_snapshots':'death-snapshots.jsonl'},'code':git_state(),'arguments':vars(args),
            'continuation_of':recovered.get('run_id') if recovered else None,
            'interrupted_round':recovered.get('interrupted_round') if recovered else None,
            'recovery':recovered.get('recovery') if recovered else None,
            'provenance':origin,'planned_learning_window_hours':72,'learning_window_started':args.learning,
            'scientifically_validated':False}
        (audit_dir/f'run-{run_id}.json').write_text(json.dumps(run_record,indent=2)+'\n')
        def checkpoint():
            if checkpoints:
                checkpoints.save(brain,controls,game,{'run_id':run_id,'study_id':study_id,'tick':tick,
                    'total_actions':total_actions,'episodes':list(episodes),'reward':reward.__dict__.copy(),
                    **({'training':training.state()} if training else {})})
        last_checkpoint=time.monotonic()
        frozen=None;deaths=0;end_reason='error'
        print(json.dumps({'status':'running','run_id':run_id,'condition':args.condition,'port':args.port}),flush=True)
        try:
          while not stop.is_set():
            began=time.monotonic()
            before=game.observation()
            if before['finished']:
                episodes.append(before);deaths+=1;lives.finish(before,brain.sim_ms,run_id=run_id);game.new_episode()
                if observer:observer.advance(game,reset=True)
                # Death resets the world, not the brain: only pending PPL101 exposure is cancelled.
                if training:training.new_round()
                before=game.observation();lives.start(before,brain.sim_ms)
            frame=game.pixels();light=retinal_samples(frame,brain.uv)
            spectator=game.spectator() # Same pre-action state as RGB; observer path only.
            if args.condition=='blank_vision':light.fill(0)
            if args.condition=='frozen_vision':
                if frozen is None:frozen=light.copy()
                light=frozen
            # Alternate 285/286 substeps to keep neural and Doom clocks aligned
            # to <0.1 ms. Never silently skip steps when the host is slow.
            tick+=1;target=int(round(tick*10000/35));steps=target-brain.cursor
            sugar_applied=reward.active(brain.sim_ms)
            if training:counts,neural_wall=training.step(frame,steps)
            else:counts,neural_wall=brain.step(light,steps*.1,sugar=sugar_applied)
            action=controls.decode(counts,steps*.1/1000)
            if args.condition=='controls_clamped':
                applied={**action,'turn':0.,'forward':0.,'attack':False}
            else:applied=action
            score=game.act(applied);reward.observe(score,brain.sim_ms)
            if observer:observer.advance(game,action=applied)
            after=game.observation()
            if training:training.observe(before,after)
            lives.tick(before,after,applied,spectator)
            retina_change=0. if previous_light is None else float(np.abs(light-previous_light).mean());previous_light=light.copy()
            nonzero=abs(applied['turn'])>1e-9 or abs(applied['forward'])>1e-9 or applied['attack']
            total_actions+=int(nonzero)
            event={'run_id':run_id,'recorded_at_ms':int(time.time()*1000),'scenario':args.scenario,'decoder':args.decoder,'condition':args.condition,'reward_mode':args.reward,'tick':tick,'neural_ms':round(brain.sim_ms,3),'episode':game.episode,
              'game':after,
              'input_sha256':hashlib.sha256(light.tobytes()).hexdigest(),
              'source_frame_sha256':hashlib.sha256(frame.tobytes()).hexdigest(),
              'spike_counts_sha256':hashlib.sha256(counts.tobytes()).hexdigest(),
              'requested':{k:action[k] for k in ['turn','forward','attack']},
              'applied':{k:applied[k] for k in ['turn','forward','attack']},
              'readouts':action['readouts'],'reward':score,'sugar_applied':sugar_applied,
              'sugar_scheduled_for_next_step':reward.active(brain.sim_ms),'model_revision':origin['model_revision'],
              'input_episode':game.episode,'input_game_tick':game.tick-1,'output_game_tick':game.tick,
              'neural_interval_ms':round(steps*.1,3)}
            if training:event['learning']=training.telemetry()
            event['simulation_age_ms']=round(brain.sim_ms,3);event['monitor']=monitor.sums(counts);event['retina_change']=round(retina_change,6)
            audit_logger.info(json.dumps(event,separators=(',',':')))
            sample={'neural_ms':round(brain.sim_ms,3),'tick':tick,'episode':game.episode,'health':after['health'],
              'groups':event['monitor'],'retina_change':event['retina_change'],
              'retina_mean_filtered_luminance':round(float(brain.luminance.mean()),6),'action':event['applied'],
              'decoder':{r['id']:{'type':r['type'],'side':r['side'],'rate_hz':r['rate_hz'],'voltage_mv':round(float(brain.v[r['index']]),3)}
                         for r in action['readouts'] if r['type'] in ['DNp20','DNpe017']}}
            if training:
                sample['ppl101_active']=training.last_steps>0
                if transducer:sample['nociception_drive_mv']=event['learning']['nociception']['drive_mv_last_tic']
            snapshots.record(sample,brain.v)
            if after['finished']:
                context={'run_id':run_id,'episode':game.episode,'tick':tick,'damage_input':args.damage_input if training else None,
                         'decoder_rates':controls.rates.round(4).tolist()}
                if training:context|={'memory':brain.memory(),'eligibility_sum':float(brain.eligibility.sum()),'damage_state':training.state()}
                snapshots.death(context)
            timeline.append({'tick':tick,'spikes':int(counts.sum()),'action':event['applied']})
            window_counts+=counts;window_ms+=steps*.1
            now=time.monotonic()
            if now-last_publish>=1/DISPLAY_FPS:
                seq+=1;age=now-start
                history.append({'neural_ms':round(brain.sim_ms,1),'window_ms':round(window_ms,3),'counts':window_counts[display].tolist(),'population_spikes':int(window_counts.sum())})
                # Show the frame that actually supplied this action's input,
                # avoiding an image/telemetry mismatch or invented interpolation.
                jpeg=encoded_frame(frame)
                latest={'schema':1,'status':'running','run_id':run_id,'sequence':seq,
                  'generated_at_ms':int(time.time()*1000),'condition':args.condition,'decoder':args.decoder,
                  'frame':jpeg,'input_frame_sha256':event['source_frame_sha256'],
                  'display_jpeg_sha256':hashlib.sha256(base64.b64decode(jpeg.split(',',1)[1])).hexdigest(),
                  'provenance':origin,
                  'manifest':manifest,'clocks':{'wall_seconds':round(age,3),'neural_seconds':round(brain.sim_ms/1000,4),
                    'game_seconds':round(tick/35,4),'speed':round((brain.sim_ms/1000-neural_start)/age,3),'brain_step_ms':round(neural_wall*1000,3)},
                  'game':after,'episodes':list(episodes),'action':event['applied'],'readouts':action['readouts'],
                  'total_spikes':brain.total_spikes,'window_spikes':int(window_counts.sum()),'window_ms':round(window_ms,2),
                  'total_action_ticks':total_actions,'neuron_voltage_mv':{r['id']:round(float(brain.v[r['index']]),3) for r in manifest['readouts']},
                  'populations':[{'name':str(k),'neurons':len(ix),'spikes':int(window_counts[ix].sum()),
                    'mean_rate_hz':float(window_counts[ix].sum()/len(ix)/(window_ms/1000))} for k,ix in zip(group_names,groups)],
                  'retina':{'uv':brain.uv[::8].round(4).tolist(),'luminance':light[::8].round(4).tolist(),
                    'neuron_ids':[str(x) for x in brain.ids[brain.retina[::8]]], 'side':retina_sides[::8].tolist(),
                    'filtered_luminance':brain.luminance[::8].round(4).tolist(),
                    'drive_mv':brain.drive[brain.retina[::8]].round(4).tolist(),
                    'spikes_last_step':counts[brain.retina[::8]].tolist(),
                    'measurement':'Raw normalized frame luminance; not firing rate or a reconstructed subjective view.',
                    'full_sample_count':len(light),'display_stride':8},
                  'raster':{'neuron_ids':[str(brain.ids[i]) for i in display],'bins':list(history)},
                  'timeline':list(timeline),'audit':event,
                  'reward':{'mode':('damage-ppl101' if args.damage_input=='ppl101' else 'none' if args.damage_input=='none' else 'nociception-'+args.damage_input) if training else args.reward,'sugar_pulses':reward.pulses,
                    'active':training.last_steps>0 if training else reward.active(brain.sim_ms),'plasticity':args.learning},
                  'protocol':{'dt_ms':brain.dt,'lamina_bias_mv':12,'retinal_gain_mv':30,'photoreceptor_half_saturation':.02,'seed':args.seed,'replicate':'one reconstructed male',
                    'input_filter':'R1–R6 and R8 filters updated in <=10 ms bins' if training else '10 ms discrete low-pass, updated once per game interval; resulting current held for that interval',
                    'frame_timing':'JPEG of pre-action input frame; game counters are post-action; raw RGB hash differs from compressed JPEG hash',
                    'scenario':args.scenario,'episode_end':'death' if args.scenario=='combat_survival' else 'death or 60-second cap',
                    'automatic_episode_reset':True,'neural_state_persists_across_episodes':True,
                    'damage_input':args.damage_input if training else None,
                    'broadcast_capture_fps_limit':DISPLAY_FPS,'phase':phase,'study_id':study_id,
                    'learning_enabled':args.learning,'scientifically_validated':False,'model':origin['model_revision'],
                    'continuation_of':run_record['continuation_of'],'recovery':run_record['recovery'],
                    'hosting':'local broadcaster; unavailable if host sleeps or disconnects'}}
                if training:latest['learning']=event['learning']
                if spectator is not None:latest['spectator']=spectator
                broadcast.publish(latest)
                last_publish=now;window_counts.fill(0);window_ms=0
            if checkpoints and now-last_checkpoint>=args.checkpoint_seconds:
                checkpoint();last_checkpoint=time.monotonic()
            if args.max_neural_seconds and brain.sim_ms/1000-neural_start>=args.max_neural_seconds:
                end_reason='max-neural-seconds';break
            remaining=start+(brain.sim_ms/1000-neural_start)-time.monotonic()
            if remaining>0:stop.wait(remaining)
          else:end_reason='stopped'
        finally:
            try:checkpoint()
            finally:
                try:
                    snapshots.close()
                    final=game.observation() # A death not yet followed by a new round is still a completed life.
                    lives.finish(final,brain.sim_ms,censored=not final['finished'],run_id=run_id)
                except Exception:logging.getLogger('doom-audit').exception('Could not close life or death logs')
                try:
                    end={'run_id':run_id,'study_id':study_id,'ended_at_ms':int(time.time()*1000),'end_reason':end_reason,
                         'ticks':tick,'game_seconds':round(tick/35,4),'simulation_age_ms':round(brain.sim_ms,3),
                         'neural_seconds_this_run':round(brain.sim_ms/1000-neural_start,4),'deaths':deaths,
                         'final_weight_sha256':hashlib.sha256(brain.weight.tobytes()).hexdigest(),
                         **({'final_memory':brain.memory(),'final_damage_state':training.state()} if training else {})}
                    (audit_dir/f'run-{run_id}-end.json').write_text(json.dumps(end,indent=2)+'\n')
                except Exception:logging.getLogger('doom-audit').exception('Could not write run end record')
                if observer:observer.close()
                game.close();audit_handler.close();archive.close()
        if end_reason=='max-neural-seconds':
            latest={'status':'finished','generated_at_ms':int(time.time()*1000),'message':'The run completed its planned neural time.'}
            broadcast.offline(latest)
    except Exception as e:
        latest={'status':'error','generated_at_ms':int(time.time()*1000),'message':'The simulation stopped. No live data is available.'}
        broadcast.offline(latest)
        import traceback;traceback.print_exc()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        cache='no-store'
        if self.path.startswith('/observer?'):
            try:
                pose=camera_query(self.path.split('?',1)[1])
                if observer is None:raise ObserverUnavailable('No native observer')
                body=observer.render(pose)
            except ValueError:self.send_error(400);return
            except ObserverBusy:self.send_error(429);return
            except ObserverUnavailable:self.send_error(503);return
            except Exception:
                logging.getLogger('doom-observer').exception('Native observer request failed')
                self.send_error(503);return
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(body)));self.end_headers()
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass
            return
        if self.path=='/state':body=broadcast.state
        elif self.path=='/index':body=broadcast.index
        elif self.path=='/health':body=json.dumps({k:latest.get(k) for k in ['status','run_id','sequence','generated_at_ms']},separators=(',',':')).encode()
        else:
            match=re.fullmatch(r'/segments/([a-f0-9-]{36})/([0-9]{10,14})',self.path)
            body=broadcast.get_segment(*match.groups()) if match else None
            if body is None:self.send_error(404);return
            cache='public, max-age=31536000, immutable'
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control',cache)
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(body)));self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass
    def log_message(self,*args):pass

def parse_args(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8766)
    p.add_argument('--decoder',choices=['biological','bci'],default='bci')
    p.add_argument('--scenario',choices=['combat_survival','defend_the_center'],default='combat_survival')
    p.add_argument('--audit-dir',default=str(ROOT/'outputs/doom'))
    p.add_argument('--bind',default='127.0.0.1')
    p.add_argument('--checkpoint-dir');p.add_argument('--resume',action='store_true')
    p.add_argument('--checkpoint-seconds',type=int,default=300)
    p.add_argument('--model',choices=['baseline','experimental-v6'],default='baseline')
    p.add_argument('--learning',action='store_true',help='Enable explicitly unvalidated v6 memory plasticity')
    p.add_argument('--seed',type=int,default=41027);p.add_argument('--reward',choices=['off','sugar'],default='off')
    p.add_argument('--condition',choices=['intact','blank_vision','frozen_vision','retina_disconnected','all_edges_disconnected','controls_clamped'],default='intact')
    p.add_argument('--damage-input',choices=['ppl101','none',*NOCICEPTIVE_INPUTS],default='ppl101',
        help='How v6 health loss reaches the network: upstream PPL101 pulse, nothing, SNxx29 nociceptors, or matched random leg sensory neurons (same drive or calibrated spike dose)')
    p.add_argument('--nociception-gain',type=float,default=30.,
        help='mV-equivalent drive at damage_reference HP (engineering value; 30 is the lowest probed gain recruiting AN05B004 and AN09B018)')
    p.add_argument('--nociception-pulse-ms',type=float,default=200.)
    p.add_argument('--nociception-decay-ms',type=float,default=0.,help='0 keeps a constant pulse')
    p.add_argument('--nociception-damage-reference',type=float,default=20.,help='HP loss that produces the full gain')
    p.add_argument('--nociception-left-right-mode',choices=['bilateral'],default='bilateral')
    p.add_argument('--nociception-seed',type=int,help='Required seed for the random control populations')
    p.add_argument('--nociception-dose-calibration',default=str(ROOT/'outputs/doom/nociception/dose-calibration-v1.json'),
        help='Calibration record providing the random-dose-matched gain (python -m doom.nociception_probe --calibrate-dose)')
    p.add_argument('--death-snapshot-full',action='store_true',help='Also save whole-brain voltages around each death')
    p.add_argument('--max-neural-seconds',type=float,help='Automated experiments: stop cleanly after this much neural time in this process')
    args=p.parse_args(argv)
    if args.learning and args.model!='experimental-v6':p.error('Learning requires the explicit experimental-v6 model')
    if args.model=='experimental-v6' and (args.condition!='intact' or args.reward!='off' or args.decoder!='bci'):
        p.error('Live candidate requires intact RGB, no reward input, and the fixed BCI')
    if args.damage_input!='ppl101' and args.model!='experimental-v6':p.error('--damage-input requires the experimental-v6 model')
    if (args.damage_input in RANDOM_INPUTS)!=(args.nociception_seed is not None):
        p.error('--nociception-seed is required for, and only valid with, the random control damage inputs')
    nociceptive=['nociception_gain','nociception_pulse_ms','nociception_decay_ms','nociception_damage_reference','nociception_dose_calibration']
    if args.damage_input not in NOCICEPTIVE_INPUTS and any(getattr(args,k)!=p.get_default(k) for k in nociceptive):
        p.error('Nociception parameters require a sensory --damage-input')
    if args.damage_input=='random-dose-matched' and args.nociception_gain!=p.get_default('nociception_gain'):
        p.error('random-dose-matched takes its gain from the dose calibration record')
    if args.damage_input!='random-dose-matched' and args.nociception_dose_calibration!=p.get_default('nociception_dose_calibration'):
        p.error('--nociception-dose-calibration only applies to random-dose-matched')
    if args.max_neural_seconds is not None and not args.max_neural_seconds>0:p.error('--max-neural-seconds must be positive')
    if args.checkpoint_seconds<30:p.error('Checkpoint interval must be at least 30 seconds')
    if args.resume and not args.checkpoint_dir:p.error('--resume requires --checkpoint-dir')
    if args.checkpoint_dir and args.scenario!='combat_survival':p.error('Recovery requires the unlimited combat arena')
    return args

def main():
    args=parse_args()
    def shutdown_signal(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,shutdown_signal)
    worker=threading.Thread(target=run_loop,args=(args,),daemon=True);worker.start()
    server=ThreadingHTTPServer((args.bind,args.port),Handler)
    if args.max_neural_seconds is None:
        # Live broadcast: keep serving, including the offline state after an error.
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:stop.set();server.server_close();worker.join(timeout=45)
        return
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        while worker.is_alive():worker.join(1)
    except KeyboardInterrupt:pass
    finally:stop.set();server.shutdown();server.server_close();worker.join(timeout=45)
    if latest.get('status')!='finished':raise SystemExit(1)
if __name__=='__main__':main()
