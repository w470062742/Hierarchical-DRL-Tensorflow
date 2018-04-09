import logging
import os
import inspect
import sys
import glob
import utils
import logging
from abc import ABCMeta, abstractmethod, abstractproperty
from pprint import pformat

class Constants:
    SF_envs = ['SFS-v0', 'SF-v0', 'SFC-v0', 'AIM-v0']
    MDP_envs = ['stochastic_mdp-v0', 'ez_mdp-v0', 'trap_mdp-v0', 'key_mdp-v0']
    env_names = SF_envs + MDP_envs
    
   
    
class Configuration:
    def __init__(self):
        self.gl = None      #Global settings
        self.ag = None      #Agent settings
        self.env = None     #Environment settings
        
    def set_agent_settings(self, settings):
        self.ag = settings
        
    def set_environment_settings(self, settings):
        self.env = settings
        
    def set_global_settings(self, settings):
        self.gl = settings
    
    def to_dict(self):
        dictionary = {}
        for settings in ['ag', 'env', 'gl']:
            try:
                dictionary[settings] = getattr(self, settings).to_dict()
            except Exception as e:
                print(e)
                
        return dictionary
    
    def to_str(self): return pformat(self.to_dict())
    
    def print(self):
        msg =  "\n" + self.to_str()
        logging.info(msg)    
        
class GenericSettings():
        
    def update(self, new_attrs, add = False):
        """
        Add new attributes and overwrite existing ones.
        
        Args:
            new_attrs: dict ot settings object whose attributes will be added
            to the instance
        """
        if type(new_attrs) is dict:
            for key, value in new_attrs.items():
                
                if value is None or (not hasattr(self, key) and not add):
                    """When new_attrs is flags set through command line
                    parameters the default value is None so in those cases
                    we keep the instance value"""
                    continue
                else:
                    old_value = getattr(self, key) if hasattr(self, key) else '_'
                    logging.debug("Updated %s: %s -> %s", key, str(old_value),
                                                          str(value))
                    setattr(self, key, value)
                    
        elif isinstance(new_attrs, GenericSettings):
            raise NotImplementedError
        else:
            raise ValueError
                
    def to_dict(self): return vars(self).copy()
    def to_str(self): return pformat(self.to_dict())
        
    def print(self):
        msg =  "\n" + self.to_str()
        #print(msg)
        logging.info(msg)
            
    
    def to_disk(self, filepath):
        #TODO test this method
        content = self.to_str()
        with open(filepath) as fp:
            fp.write(content)

    
class GlobalSettings(GenericSettings):
    def __init__(self, new_attrs = {}):        
        self.display_prob = .01
        self.log_level = 'INFO'
        self.new_instance = True
        self.date = utils.get_timestamp()
        self.action_repeat = 1
        self.use_gpu = True
        self.gpu_fraction = '1/1'
        self.random_seed = 7
        self.root_dir = os.path.normpath(os.path.join(os.path.dirname(
                                        os.path.realpath(__file__)), ".."))
        self.env_dirs = [
            os.path.join(self.root_dir, '..', 'Environments','gym-stochastic-mdp'),
            os.path.join(self.root_dir, '..', 'Environments','gym-stochastic-mdp',
                                               'gym_stochastic_mdp','envs'),
            os.path.join(self.root_dir, '..', 'Environments','SpaceFortress',
                                               'gym_space_fortress','envs'),
            os.path.join(self.root_dir, '..', 'Environments','SpaceFortress',
                                               'gym_space_fortress', 'envs',
                                               'space_fortress'),
            os.path.join(self.root_dir, '..', 'Environments','SpaceFortress')]
        #TODO clean path loadings
        self.ignore = ['display','new_instance','env_dirs','root_dir', 'ignore',
                       'use_gpu', 'gpu_fraction', 'is_train', 'prefix']
        self.attrs_in_dir = ['gl.date','env.env_name','ag.agent_type',
                             'env.right_failure_prob', 'env.total_states']
        self.checkpoint_dir = '' #TODO
        self.logs_dir = '' #TODO
        self.settings_dir = '' #TODO
        self.randomize = False
        self.update(new_attrs)
        

class AgentSettings(GenericSettings):
    def __init__(self, scale):
        self.scale = scale
        self.mode = 'train'
        
    
    def scale_attrs(self, attr_list):
        for attr in attr_list:
            normal = getattr(self, attr)
            scaled = self.scale * normal
            setattr(self, attr, scaled)
            
class HumanSettings(GenericSettings):
    def _init_(self):
       pass 
        
        
class DQNSettings(AgentSettings):
    """
    Configuration of the DQN agent
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.agent_type = 'dqn'
        self.max_step = 500 * self.scale
        self.memory_size = 500 * self.scale
        
        self.batch_size = 32
        self.random_start = 30
        
        self.discount = 0.99
        self.target_q_update_step = 1 * self.scale
        self.learning_rate = 0.001
        self.learning_rate_minimum = 0.00025
        self.learning_rate_decay = 0.93
        self.learning_rate_decay_step = 5 * self.scale
        
        self.ep_end = 0.1
        self.ep_start = 1.
        self.ep_end_t = self.memory_size
        
        self.history_length = 1
        self.train_frequency = 4
        self.learn_start = 5. * self.scale
        
        self.architecture = [500, 500, 500]
        
        
        self.test_step = 5 * self.scale
        self.save_step = self.test_step * 10
        
        self.activation_fn = 'relu'
        self.prefix = ''
        
        
    
class hDQNSettings(AgentSettings):
    """
    Configuration
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.agent_type = 'hdqn'
        self.mc = MetaControllerSettings(*args, **kwargs)
        self.c = ControllerSettings(*args, **kwargs)
        self.random_start = 30
    

    def to_dict(self):       
        dictionary = vars(self).copy()
        dictionary['mc'] = self.mc.to_dict()
        dictionary['c'] = self.c.to_dict()
        return dictionary
        



class ControllerSettings(AgentSettings):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.history_length = 1
        
        self.memory_size = 500 * self.scale
        
        self.max_step = 500 * self.scale
        
        self.batch_size = 32
        self.random_start = 30
        
        self.discount = 0.99
        self.target_q_update_step = 1 * self.scale
        self.learning_rate = 0.001
        self.learning_rate_minimum = 0.00025
        self.learning_rate_decay = 0.94
        self.learning_rate_decay_step = 5 * self.scale
        
        self.ep_end = 0.1
        self.ep_start = 1.
        self.ep_end_t = self.memory_size
        
        self.train_frequency = 4
        self.learn_start = 5. * self.scale
        
        self.architecture = [500, 500, 500, 500, 500, 500, 500, 500]
        self.test_step = 5 * self.scale
        self.save_step = self.test_step * 10
        self.activation_fn = 'relu'
        
        self.ignore = ['ignore']
        self.prefix = 'c'
    
    
    
    
class MetaControllerSettings(AgentSettings):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.history_length = 1    
        
        self.memory_size = 500 * self.scale
         
        #max_step = 5000 * scale
        
        self.batch_size = 64
        self.random_start = 30
        
        self.discount = 0.99
        self.target_q_update_step = 1 * self.scale
        self.learning_rate = 0.001
        self.learning_rate_minimum = 0.00025
        self.learning_rate_decay = 0.94
        self.learning_rate_decay_step = 5 * self.scale
        
        self.ep_end = 0.1
        self.ep_start = 1.
        self.ep_end_t = self.memory_size
        
        self.train_frequency = 4
        self.learn_start = 5. * self.scale
        
        self.architecture = [500, 500, 500]
        
        self.test_step = 5 * self.scale
        self.save_step = self.test_step * 10
        self.activation_fn = 'relu'
        
        self.ignore = ['ignore']
        self.prefix = 'mc'
    
class EnvironmentSettings(GenericSettings):
    def __init__(self):
        self.env_name = ''   
        self.random_start = False 
        self.action_repeat = 1     
        self.right_failure_prob = 0.
class EZ_MDPSettings(EnvironmentSettings):
    def __init__(self, new_attrs):
        super().__init__()
        self.total_states = 6
        self.initial_state = 1
        self.terminal_states = [0, 5]
        self.total_actions = 2
        self.right_failure_prob = 0.
        self.update(new_attrs)
       
class Key_MDPSettings(EnvironmentSettings):
     def __init__(self, new_attrs): 
        super().__init__()
        self.factor = 3
        self.initial_state = 4
        self.total_states = self.factor ** 2
        self.update(new_attrs)
        
        
class Stochastic_MDPSettings(EnvironmentSettings):
    def __init__(self, new_attrs):
        super().__init__()
        self.total_states = 6
        self.initial_state = 1
        self.terminal_states = [0]
        self.total_actions = 2
        self.right_failure_prob = 0.5
        self.update(new_attrs)
           
        
          
class Trap_MDPSettings(EnvironmentSettings):
    def __init__(self, new_attrs):
        super().__init__()
        self.total_states = 6
        self.initial_state = 1
        self.terminal_states = [0, 5]
        self.total_actions = 2
        self.update(new_attrs)
     
        self.trap_states = [3, 4]
        
        
    
class SpaceFortressSettings(EnvironmentSettings):
    def __init__(self, new_attrs):
        super().__init__()
        self.no_direction = False
        self.libsuffix = ""
        
        self.screen_width = 84
        self.screen_height = 84
        self.update(new_attrs)





