"""Doom boundary: the neural input path receives pixels, never object state."""
from pathlib import Path
import hashlib
import numpy as np
import vizdoom as vzd

class Game:
    def __init__(self,seed=41027,scenario='defend_the_center',spectator=False,observer_engine=None):
        self.game=vzd.DoomGame()
        # Used only by the isolated spectator mirror. The neural game always
        # uses the installed, unmodified ViZDoom executable.
        if observer_engine:self.game.set_vizdoom_path(str(observer_engine))
        directory=Path(__file__).parent/'scenarios' if scenario=='combat_survival' else Path(vzd.scenarios_path)
        cfg=directory/(scenario+'.cfg')
        wad=directory/(scenario+'.wad')
        self.scenario=scenario
        iwad=Path(vzd.__file__).parent/'freedoom2.wad'
        self.game.load_config(str(cfg))
        self.game.set_doom_scenario_path(str(wad.resolve()))
        self.game.set_doom_game_path(str(iwad))
        self.assets={'vizdoom_version':vzd.__version__,'scenario':scenario,
          'sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [cfg,wad,iwad]}}
        if scenario=='combat_survival':
            import json
            self.assets['rules']=json.loads((directory/'combat_survival.json').read_text())
        self.game.set_window_visible(False);self.game.set_sound_enabled(False)
        self.game.set_screen_format(vzd.ScreenFormat.RGB24)
        self.game.set_screen_resolution(vzd.ScreenResolution.RES_640X480)
        self.game.set_mode(vzd.Mode.PLAYER)
        self.game.set_depth_buffer_enabled(bool(observer_engine));self.game.set_labels_buffer_enabled(False)
        self.spectator_enabled=spectator
        self.game.set_automap_buffer_enabled(False);self.game.set_objects_info_enabled(spectator)
        self.game.set_sectors_info_enabled(spectator)
        self.game.set_available_buttons([vzd.Button.TURN_LEFT_RIGHT_DELTA,vzd.Button.MOVE_FORWARD_BACKWARD_DELTA,vzd.Button.ATTACK])
        self.game.set_button_max_value(vzd.Button.TURN_LEFT_RIGHT_DELTA,6)
        self.game.set_button_max_value(vzd.Button.MOVE_FORWARD_BACKWARD_DELTA,20)
        self.game.clear_available_game_variables()
        # These are observer/reinforcement outputs only. Never fed to controls.
        self.game.add_available_game_variable(vzd.GameVariable.HEALTH)
        self.game.add_available_game_variable(vzd.GameVariable.KILLCOUNT)
        self.game.add_available_game_variable(vzd.GameVariable.AMMO2)
        self.game.add_available_game_variable(vzd.GameVariable.HITCOUNT)
        self.game.set_episode_timeout(0 if scenario=='combat_survival' else 35*60)
        self.game.set_seed(seed);self.game.init()
        self.episode=0;self.tick=0;self.episodes=[];self.new_episode()
    def new_episode(self):
        self.game.new_episode();self.episode+=1;self.tick=0
    def pixels(self):
        state=self.game.get_state()
        if state is None:raise RuntimeError('Episode finished; reset is required')
        return state.screen_buffer.copy()
    def act(self,action):
        # The adapter is the only caller of make_action. No human keystrokes.
        reward=self.game.make_action([action['turn'],action['forward'],int(action['attack'])],1)
        self.tick+=1
        return float(reward)
    def spectator(self):
        """Observer-only pre-action geometry. Never passed to the neural adapter.

        Coordinates/angles are unmodified engine values (Doom units/degrees).
        No observer action, rendering or timer can advance the engine.
        """
        if not self.spectator_enabled:return None
        state=self.game.get_state()
        if state is None:return None
        def value(name):return float(self.game.get_game_variable(getattr(vzd.GameVariable,name)))
        objects=[{'id':int(o.id),'name':o.name,'x':float(o.position_x),'y':float(o.position_y),
                  'z':float(o.position_z),'angle':float(o.angle)} for o in state.objects]
        sectors=[{'floor':float(s.floor_height),'ceiling':float(s.ceiling_height),
                  'lines':[[float(l.x1),float(l.y1),float(l.x2),float(l.y2)] for l in s.lines]}
                 for s in state.sectors]
        if len(objects)>256 or len(sectors)>32 or any(len(s['lines'])>128 for s in sectors):
            return None # Unsupported map: never silently truncate the scene.
        return {'version':1,'timing':'pre-action','episode':self.episode,'tick':self.tick,
                'player':{k:value(v) for k,v in [('x','POSITION_X'),('y','POSITION_Y'),
                    ('z','POSITION_Z'),('angle','ANGLE'),('pitch','PITCH')]},
                'objects':objects,'sectors':sectors}
    def observation(self):
        g=self.game
        result={'episode':self.episode,'tick':self.tick,'finished':g.is_episode_finished(),
          'health':int(g.get_game_variable(vzd.GameVariable.HEALTH)),
          'kills':int(g.get_game_variable(vzd.GameVariable.KILLCOUNT)),
          'ammo':int(g.get_game_variable(vzd.GameVariable.AMMO2)),
          'hits':int(g.get_game_variable(vzd.GameVariable.HITCOUNT)),
          'score':float(g.get_total_reward())}
        if self.scenario=='combat_survival':
            for name,var in [('enemies',vzd.GameVariable.USER1),('enemies_spawned',vzd.GameVariable.USER2),
                             ('ammo_pickups',vzd.GameVariable.USER3),('ammo_spawned',vzd.GameVariable.USER4),
                             ('imps',vzd.GameVariable.USER5),('zombies',vzd.GameVariable.USER6)]:
                result[name]=int(g.get_game_variable(var))
        return result
    def close(self):self.game.close()

def retinal_samples(rgb,uv):
    """Bilinear luminance at receptor samples only. No scene interpretation."""
    h,w=rgb.shape[:2];x=uv[:,0]*(w-1);y=uv[:,1]*(h-1)
    x0=x.astype(int);y0=y.astype(int);x1=np.minimum(x0+1,w-1);y1=np.minimum(y0+1,h-1)
    dx=x-x0;dy=y-y0
    def linear_luma(pixels):
        p=pixels.astype(np.float32)/255
        p=np.where(p<=.04045,p/12.92,((p+.055)/1.055)**2.4)
        return p@np.asarray([.2126,.7152,.0722],dtype=np.float32)
    return ((1-dx)*(1-dy)*linear_luma(rgb[y0,x0])+dx*(1-dy)*linear_luma(rgb[y0,x1])+(1-dx)*dy*linear_luma(rgb[y1,x0])+dx*dy*linear_luma(rgb[y1,x1])).astype(np.float32)
