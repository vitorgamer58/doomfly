"""Full-graph candidate memory dynamics with explicit stimulation and checkpoints."""
import ctypes as C
import hashlib,json,math,subprocess,sys,time
from pathlib import Path
import numpy as np
from doom.native import NativeBrain
from .common import ROOT, GRAPH, OUT, digest, save_json
from .circuit import identify

SOURCE=Path(__file__).with_name('kernel.cpp')
LIBRARY=OUT/('libmemory.dylib' if sys.platform=='darwin' else 'libmemory.so')
MODEL='gamma1-eligibility-ltd-v1'
PARAMETERS={'eligibility_tau_ms':1000.,'eta_per_pair':.001,'minimum_efficacy_fraction':.1,
    'dopamine_trace_tau_ms':100.,'dt_ms':.1,
    'interpretation':'Chosen phenomenological parameters, not fitted to fly physiology or Doom performance. LTD-only; no consolidation, recovery, extinction or prediction-error circuit.'}


def build():
    sha=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    metadata=LIBRARY.with_suffix(LIBRARY.suffix+'.json')
    if LIBRARY.exists() and metadata.exists():
        record=json.loads(metadata.read_text())
        if record['source_sha256']==sha and record['binary_sha256']==hashlib.sha256(LIBRARY.read_bytes()).hexdigest():return record
    LIBRARY.parent.mkdir(parents=True,exist_ok=True)
    temp=LIBRARY.with_suffix(LIBRARY.suffix+'.partial')
    if sys.platform=='win32':
        subprocess.run(['clang++','-O3','-std=c++17','-shared',str(SOURCE),'-o',str(temp),
          '-Xlinker','/EXPORT:memory_advance'],check=True)
        flags=['-O3','-std=c++17','-shared','-Xlinker','/EXPORT:memory_advance']
    else:
        subprocess.run(['clang++','-O3','-std=c++17','-shared','-fPIC',str(SOURCE),'-o',str(temp)],check=True)
        flags=['-O3','-std=c++17','-shared','-fPIC']
    temp.replace(LIBRARY)
    record={'model':MODEL,'source_sha256':sha,'binary_sha256':hashlib.sha256(LIBRARY.read_bytes()).hexdigest(),
            'flags':flags}
    save_json(metadata,record);return record


class MemoryBrain(NativeBrain):
    def __init__(self,path=GRAPH,*,eta=.001,circuit=None):
        super().__init__(path)
        self.build=build();self.library=C.CDLL(str(LIBRARY));self.advance=self.library.memory_advance
        self.advance.argtypes=[C.c_int]+[C.c_void_p]*11+[C.c_int,C.c_float]+[C.c_void_p]*5+[
            C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p,C.c_int]+[C.c_void_p]*4+[
            C.c_float,C.c_float,C.c_float,C.c_int,C.c_void_p,C.c_void_p]
        self.advance.restype=None
        self.circuit=identify(self) if circuit is None else circuit
        self.eta=float(eta)
        if not math.isfinite(self.eta) or self.eta<0:raise ValueError('Finite nonnegative eta required')
        self.eligibility=np.zeros(self.n,dtype=np.float64)
        self.eligibility_last=np.zeros(self.n,dtype=np.int64)
        self.modulation=np.zeros(self.n,dtype=np.float32)
        self.modulation_last=np.zeros(self.n,dtype=np.int64)
        self.baseline_plastic=self.weight[self.circuit['edges']].copy()
        self.initial_weight_sha256=digest(self.weight)
        self.fields=['v','g','refractory','drive','previous_drive','queue','queue_count','counts',
            'luminance','active','active_flag','nactive','last','eligibility','eligibility_last','modulation','modulation_last']
        self.initial={k:getattr(self,k).copy() for k in self.fields}

    def reset(self,keep_memory=False):
        for k,v in self.initial.items():getattr(self,k)[:]=v
        self.cursor=0;self.sim_ms=0.;self.total_spikes=0
        if not keep_memory:self.weight[self.circuit['edges']]=self.baseline_plastic

    def step(self,luminance,duration_ms,*,learning=False,stimulation=None,lamina_bias=12.):
        light=np.asarray(luminance)
        if light.shape!=(len(self.retina),) or not np.isfinite(light).all():raise ValueError('Invalid retinal input')
        steps=round(duration_ms/self.dt)
        if not math.isfinite(duration_ms) or steps<1 or not math.isfinite(lamina_bias):raise ValueError('Invalid interval/current')
        self.luminance+=(1-math.exp(-steps*self.dt/10))*(np.clip(light,0,1)-self.luminance)
        self.drive.fill(0);self.drive[self.lamina]=lamina_bias
        self.drive[self.retina]=30*self.luminance/(.02+self.luminance)
        if stimulation is not None:
            pulses=stimulation if isinstance(stimulation,list) else [stimulation]
            for indices,current in pulses:
                ix=np.asarray(indices,dtype=np.int32)
                if ix.ndim!=1 or np.any(ix<0) or np.any(ix>=self.n) or not math.isfinite(current):raise ValueError('Invalid external stimulation')
                self.drive[ix]+=current
        self.counts.fill(0);clock=np.asarray([self.cursor],dtype=np.int64);c=self.circuit
        arrays=[self.ptr,self.post,self.weight,self.v,self.g,self.refractory,self.drive,self.previous_drive,self.queue,self.queue_count,clock]
        start=time.perf_counter()
        self.advance(self.n,*[x.ctypes.data for x in arrays],steps,self.dt,
            *[getattr(self,k).ctypes.data for k in ['counts','active','active_flag','nactive','last']],
            c['kc_mask'].ctypes.data,c['dan_index'].ctypes.data,self.eligibility.ctypes.data,self.eligibility_last.ctypes.data,
            len(c['edges']),c['edges'].ctypes.data,c['pre'].ctypes.data,self.baseline_plastic.ctypes.data,c['gain'].ctypes.data,
            self.eta,PARAMETERS['eligibility_tau_ms'],PARAMETERS['minimum_efficacy_fraction'],int(learning),
            self.modulation.ctypes.data,self.modulation_last.ctypes.data)
        elapsed=time.perf_counter()-start
        self.cursor=int(clock[0]);self.sim_ms=self.cursor*self.dt;self.total_spikes+=int(self.counts.sum())
        return self.counts.copy(),elapsed

    def memory(self):
        w=self.weight[self.circuit['edges']];fraction=w/self.baseline_plastic
        return {'plastic_edges':len(w),'changed_edges':int(np.count_nonzero(w!=self.baseline_plastic)),
            'mean_efficacy':float(fraction.mean()),'minimum_efficacy':float(fraction.min()),
            'sha256':digest(w),'model':MODEL}

    def checkpoint(self,path):
        metadata={'model':MODEL,'build':self.build,'eta':self.eta,'parameters':PARAMETERS,'cursor':self.cursor,
            'total_spikes':self.total_spikes,'graph_ids_sha256':digest(self.ids),'graph_ptr_sha256':digest(self.ptr),
            'graph_post_sha256':digest(self.post),'plastic_edges_sha256':digest(self.circuit['edges']),
            'configuration_sha256':self.configuration_signature()}
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        np.savez(path,metadata=json.dumps(metadata),weight=self.weight,**{k:getattr(self,k) for k in self.fields})

    def restore(self,path):
        with np.load(path,allow_pickle=False) as a:
            m=json.loads(str(a['metadata']))
            expected={'model':MODEL,'build':self.build,'eta':self.eta,'parameters':PARAMETERS,
                'graph_ids_sha256':digest(self.ids),'graph_ptr_sha256':digest(self.ptr),'graph_post_sha256':digest(self.post),
                'plastic_edges_sha256':digest(self.circuit['edges']),
                'configuration_sha256':self.configuration_signature()}
            if any(m.get(k)!=v for k,v in expected.items()):raise ValueError('Checkpoint provenance mismatch')
            for k in ['weight',*self.fields]:
                if a[k].shape!=getattr(self,k).shape or a[k].dtype!=getattr(self,k).dtype:raise ValueError('Checkpoint array mismatch')
            for k in ['weight',*self.fields]:getattr(self,k)[:]=a[k]
            self.cursor=int(m['cursor']);self.sim_ms=self.cursor*self.dt;self.total_spikes=int(m['total_spikes'])

    def configuration_signature(self):
        # Equal cell IDs and CSR endpoints alone do not imply equal input
        # geometry, original efficacies or compartment assignment.
        return {'initial_weight':self.initial_weight_sha256,
                **{k:digest(getattr(self,k)) for k in ['retina','uv','lamina','sugar']},
                **{k:digest(self.circuit[k]) for k in ['pre','gain','kc_mask','dan_index']}}
