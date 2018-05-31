import os
import tensorflow as tf
import numpy as np
import utils
import shutil
from functools import reduce
import random
from utils import linear, pp
from configuration import Constants as CT

from environment import Environment
class Epsilon():
    def __init__(self):
        pass
    
    def setup(self, start_value, end_value, start_t, end_t, learn_start):
        """
        Sets up linear decay of epsilon
        """
        self.start = start_value
        self.end = end_value
        self.end_t = end_t
        
        self.learn_start = learn_start
        self.step = start_t
        
    def steps_value(self, step, learn_start = None):
        """
        Epsilon linear decay.
        Returns the epsilon value for a given step according to the setup
        """
        if learn_start is None:
            learn_start = self.learn_start
        epsilon = self.end + \
                max(0., (self.start - self.end) * \
                 (self.end_t -max(0., step - learn_start)) / self.end_t)
        assert 0 <= epsilon <= 1, epsilon
        return epsilon
    
    def successes_value(self, successes, attempts):
        """
        Epsilon goal success decay
        Returns the epsilon value for a given number of successes / attempts
        ratio
        """
        epsilon = 1. - successes / (attempts + 1)
        
        assert epsilon > 0, str(epsilon) + ', '+ str(successes) + ', ' + str(attempts)

        return epsilon        
    

        
    
class Agent(object):
    """Abstract object representing an Reader model."""
    def __init__(self, config):
        self._saver = None
        self.config = config
        self.output = ''
        
    def rebuild_environment(self):
        if self.m.is_SF:
            self.environment = Environment(self.config)
    
    def display_environment(self, observation):
        if self.m.is_SF:
            self.environment.gym.render()
            self.add_output('')
            return
#        if self.m.is_hdqn:
#            observation = self.c_history.get()[-1]
#        else:
#            observation = self.history.get()[-1]
     
        if self.environment.env_name == 'key_mdp-v0':
            out =  observation.reshape(self.environment.gym.shape) 
            
        else:
            out = self.environment.gym.one_hot_inverse(observation)
        msg = '\nS:\n%s' % str(out)
        self.add_output(msg)
        
    def process_info(self, info):
        if self.environment.env_name == 'SF-v0':
            self.m.fortress_hits += info['fortress_hits']
            
    def play(self):
        self.train()
        
    def is_playing(self):
        return self.ag.mode == 'play'
    
    def update_target_q_network(self, prefix):
        """
        Copies the parameters of the online network to the offile (target)
        network
        """
        #prefix = self.extend_prefix(prefix)
        w = self.get(prefix, 'w')
        target_w_assign_op = self.get(prefix, 'target_w_assign_op')
        target_w_input = self.get(prefix, 'target_w_input')
        for name in w.keys():
#            print(name)
            parameters = w[name].eval()
#            parameters_target = self.target_w[name].eval()
#            print(parameters)
#            print("******")
#            print(parameters_target)
            target_w_assign_op[name].eval(
                            {target_w_input[name]: parameters})
            
    def is_testing_time(self, prefix):
        if not self.is_ready_to_learn(prefix = prefix):
            return False
        ag = self.get(prefix, 'ag')
        step = self.get(prefix, 'step')
        return step % ag.test_step == ag.test_step - 1 
                  
    def extend_prefix(self, prefix):
        """
        Adds underscore to prefix if needed
        The prefix refer to a specific module: controller, meta-controller for
        hdqn or nothing for the baseline dqn
        
        params:
            prefix: string ('', 'mc', 'c')
        returns:
            modified prefix
        """
        return prefix + '_' if prefix != '' else prefix
        
    def is_ready_to_learn(self, prefix):
        """
        Checks if all the requirements for starting to update the network
        parameters are met
        """
        if self.is_playing():
            return False
            
        #prefix = prefix + '_' if prefix != '' else prefix
        #prefix = self.extend_prefix(prefix)
        memory = self.get(prefix, "memory")
        current_step = self.get(prefix, "step")
        start_step = self.get(prefix, "start_step")
        ag = self.get(prefix, 'ag')
       
        is_ready = current_step > start_step + ag.learn_start and \
                                memory.count > ag.memory_minimum
        if prefix == 'mc':
            #MC only starts learning if C knows how to achieve goals
            is_ready = is_ready and self.c_learnt                                
        return is_ready
    def new_episode(self):
        """
        Creates a new episode
        
        returns:
            float array with the first environments observation
        """
        screen, _, _, _ = self.environment.new_game()
        # Decide if this episode will be displayed
        self.display_episode = random.random() < self.gl.display_prob        
        return screen      
    
    def add_output(self, txt):
        self.output += txt
        
    def console_print(self, new_obs, action, reward, intrinsic_reward = None):
        """
        Auxiliar function for printing information while training
        it is not useful in SF
        """
        self.display_environment(new_obs)
        msg = '\nA: %d\nR: %.2f' % (action, reward)
        if self.m.is_hdqn:
            extra = ', G: %d, IR: %.2f' % (self.current_goal.n, intrinsic_reward)
            if intrinsic_reward in [1, 0.99]:
                extra += ' Goal accomplished!'
            msg += extra
        self.add_output(msg)
        if not self.m.is_SF:
            print(self.output)
        
    def console_print_terminal(self, reward, observation):
        """
        Auxiliar function for printing information while training and
        particularly at the end of an episode
        it is not useful in SF
        """
        if self.m.is_hdqn:
            perc = round(100 * self.c_step / self.c_ag.max_step, 4)
            ep_r = self.m.mc_ep_reward
        else:
            perc = round(100 * self.step / self.ag.max_step, 4)
            ep_r = self.m.ep_reward
        if self.environment.env_name == 'key_mdp-v0':
            out =  observation.reshape(self.environment.gym.shape) 
        elif self.config.env.env_name in CT.SF_envs:
            out = ''
        else:
            out = self.environment.gym.one_hot_inverse(observation)
        msg = '\nS:\n%s\nEP_R: %.2f' % (str(out), ep_r)
        if reward == 1:
            msg += "\tSUCCESS"
        msg += "\n________________ " + str(perc) + "% ________________"[:150]
        self.add_output(msg)
        if not self.m.is_SF:
            print(self.output)
        

            
    def setup_summary(self, scalar_summary_tags, histogram_summary_tags):    
        """
        Sets up the tensorboard summaries for monitoring the training
        
        params:
            scalar_summary_tags: list of strings with the names of scalars
            histogram_summary_tags: list of strings with the name of the
                histograms
        
        """        
        with tf.variable_scope('summary'):
            

            self.summary_placeholders = {}
            self.summary_ops = {}
            
            for tag in scalar_summary_tags:
                self.summary_placeholders[tag] = tf.placeholder(
                                'float32', None, name=tag)
                self.summary_ops[tag]    = tf.summary.scalar("%s-/%s" % \
                        (self.environment.env_name, tag), self.summary_placeholders[tag])            

            for tag in histogram_summary_tags:
                self.summary_placeholders[tag] = tf.placeholder('float32',
                                         None, name=tag)
                self.summary_ops[tag]    = tf.summary.histogram(tag,
                                            self.summary_placeholders[tag])
            
            #print("Scalars: ", ", ".join(scalar_summary_tags))
            #print("Histograms: ", ", ".join(histogram_summary_tags))
        self.writer = tf.summary.FileWriter(self.logs_dir, self.sess.graph)
    def get(self, prefix, attr_basename):
        extended_prefix = self.extend_prefix(prefix)
        attr_name = pp(extended_prefix, attr_basename)
        attr = getattr(self, attr_name)
        return attr
    def set(self, prefix, attr_basename, value):
        extended_prefix = self.extend_prefix(prefix)
        attr_name = pp(extended_prefix, attr_basename)
        setattr(self, attr_name, value)
        
    def learn_if_ready(self, prefix):
        if not self.is_ready_to_learn(prefix = prefix):
            return
        #prefix = self.extend_prefix(prefix)
      
        
        flag_start_training = self.get(prefix, 'flag_start_training')
        step = self.get(prefix, 'step')
        cnf = self.get(prefix, 'ag')
        
        memory = self.get(prefix, 'memory')
        #target_q_update_step = self.get(prefix, 'target_q_update_step')
        #update_target_q_network = self.get(prefix, 'update_target_q_network')
        q_learning_mini_batch = self.get(prefix, 'q_learning_mini_batch')
        
        if not flag_start_training:
                self.set(prefix, 'flag_start_training', True)
                name = prefix.upper() if prefix != '' else 'agent'
                print("\nLearning of %s started at step %d with %d experiences"\
                                      % (name, step, memory.count))
        
        if step % cnf.train_frequency == 0:
            q_learning_mini_batch()

        if step % cnf.target_q_update_step == cnf.target_q_update_step - 1:
            self.update_target_q_network(prefix)
            
        if prefix == 'mc':
            #Start mc_epsilon annealing
            self.mc_epsilon.learn_start = self.c_step
            
    def generate_target_q_t(self, prefix, reward, s_t_plus_1, terminal, g_t_plus_1 = None):
        """
        Generates y_true that will be used for computing the loss and be
        able to train.
        
        params:
            
        """
        #prefix = self.extend_prefix(prefix)
        
        
        target_s_t = self.get(prefix, 'target_s_t')
        if self.config.ag.double_q:
            #DOUBLE Q LEARNING
            #Get object references
            q_action = self.get(prefix, 'q_action')
            s_t = self.get(prefix, 's_t')
            target_q_with_idx = self.get(prefix, 'target_q_with_idx')
            target_q_idx = self.get(prefix, 'target_q_idx')
            
            #Predict action with ONLINE Q network
            q_action_input = {s_t: s_t_plus_1}
            if prefix == 'c': #Add goal to input
                q_action_input[self.c_g_t] = g_t_plus_1
            pred_action = q_action.eval(q_action_input)
            
            #Estimate value of predicted action with TARGET Q network
            target_q_with_idx_input = {
                    target_s_t: s_t_plus_1,
                    target_q_idx: [[idx, pred_a] for idx, pred_a in \
                                                       enumerate(pred_action)]}
            if prefix == 'c': #Add goal to input
                target_q_with_idx_input[self.c_target_g_t] = g_t_plus_1
            q_t_plus_1_with_pred_action = target_q_with_idx.eval(target_q_with_idx_input)
       
            terminal, reward = np.array(terminal), np.array(reward)
            target_q_t = (1. - terminal) * self.ag.discount * \
                                        q_t_plus_1_with_pred_action + reward
        else:
            # No double
            target_q = self.get(prefix, 'target_q')
            terminal = np.array(terminal) + 0.
            target_q_input = {target_s_t: s_t_plus_1}
            if prefix == 'c':
                target_q_input[self.c_target_g_t] = g_t_plus_1
            q_t_plus_1 = target_q.eval(target_q_input)
    
            max_q_t_plus_1 = np.max(q_t_plus_1, axis=1)
            target_q_t = (1. - terminal) * self.ag.discount * max_q_t_plus_1 + reward
        
        return target_q_t        
    def add_dueling(self, prefix, input_layer):
        #print("ADDING due", prefix)
        if prefix in ['', 'target']:
            #DQN
            architecture = self.config.ag.architecture_duel
            output_length = self.environment.action_size
        else:
            #HDQN
            if prefix in ['mc', 'mc_target']:
                architecture = self.mc_ag.architecture_duel
                output_length = self.ag.goal_size
            elif prefix in ['c', 'c_target']:
                architecture = self.c_ag.architecture_duel
                output_length = self.environment.action_size
            else:
                assert 0
        
        parameters = self.get(prefix, 'w')
#        prefix = prefix.replace("target_", "")
        last_layer = input_layer
        
        #print("adding dense into ", prefix+'w')
        value_hid, histograms_v = self.add_dense_layers(
                        architecture = architecture,
                        input_layer = last_layer,
                        parameters = parameters,
                        name_aux = 'value_hid_')
        adv_hid, histograms_a = self.add_dense_layers(
                        architecture = architecture,
                        input_layer = last_layer,
                        parameters = parameters,
                        name_aux = 'adv_hid_')
        aux1 = 'value_out'
        aux2 = 'adv_out'
        
        value, w_val, b_val = linear(value_hid, 1, name= aux1)
        adv, w_adv, b_adv = linear(adv_hid, output_length,
                                           name= aux2)
        parameters[aux1 + "_w"] = w_val
        parameters[aux1 + "_b"] = b_val
        parameters[aux2 + "_w"] = w_adv
        parameters[aux2 + "_b"] = b_adv
        q = value + (adv - tf.reduce_mean(adv, reduction_indices = 1,
                                          keepdims = True))
        #print(q)
        return q    
     
    def inject_summary(self, tag_dict, step):

        summary_str_lists = self.sess.run(
                    [self.summary_ops[tag] for tag in tag_dict.keys()],
                    {self.summary_placeholders[tag]: value for tag, value \
                                                          in tag_dict.items()})
        for summary_str in summary_str_lists:
            self.writer.add_summary(summary_str, step)
    def show_attrs(self):
        import pprint
        attrs = vars(self).copy()
        try:
            del attrs['output']
        except:
            pass
        pprint.pprint(attrs)
        
    def build_optimizer(self, prefix):
        if prefix == '':
            action_space_size = self.environment.action_size
            cnf = self.ag
        elif prefix == 'mc':
            action_space_size = self.ag.goal_size
            cnf = self.mc_ag
        elif prefix == 'c':
            action_space_size = self.environment.action_size
            cnf = self.c_ag
        else:
            assert 0
        prefix = self.extend_prefix(prefix)
        with tf.variable_scope(pp(prefix, 'optimizer')):
            if self.ag.pmemory:
                loss_weight_name = pp(prefix, 'loss_weight')
                loss_weight = tf.placeholder('float32', [None],
                                             name = loss_weight_name)
                setattr(self, loss_weight_name, loss_weight)
                
            target_q_t_name = pp(prefix, 'target_q_t')
            target_q_t = tf.placeholder('float32', [None],
                                               name=target_q_t_name)
            setattr(self, target_q_t_name, target_q_t)
            action_name = pp(prefix, 'action')
            action = tf.placeholder('int64', [None],
                                            name = action_name)
            setattr(self, action_name, action)
            action_one_hot_name = pp(prefix, 'action_one_hot')
            action_one_hot = tf.one_hot(action, action_space_size,
                                       1.0, 0.0, name = action_one_hot_name)
            setattr(self, action_one_hot_name, action_one_hot)
            
            q_acted_name = pp(prefix, 'q_acted')
            q = getattr(self, pp(prefix, 'q'))
            q_acted = tf.reduce_sum(q * action_one_hot,
                                   reduction_indices = 1, name = q_acted_name)
            td_error_name = pp(prefix, 'td_error')
            td_error = tf.abs(target_q_t - q_acted)
            setattr(self, td_error_name, td_error)
            #mc_delta = self.mc_target_q_t - mc_q_acted

            #self.global_step = tf.Variable(0, trainable=False)
            loss_aux_name = pp(prefix, 'loss_aux')
            loss_name = pp(prefix, 'loss')
            if self.ag.pmemory:
                loss_function = utils.weighted_huber_loss
                loss_weight = getattr(self, pp(prefix, 'loss_weight'))
            else:
                loss_function = utils.huber_loss
                loss_weight = None
            
            loss_aux = loss_function(TD      = td_error,
                                     weights = loss_weight)
            setattr(self, loss_aux_name, loss_aux)
            loss = tf.reduce_mean(loss_aux, name = loss_name)
            setattr(self, loss_name, loss)
            
            learning_rate_step_name = pp(prefix, 'learning_rate_step')
            learning_rate_step = tf.placeholder('int64', None,
                                            name = learning_rate_step_name)
            setattr(self, learning_rate_step_name, learning_rate_step)
            
            
            learning_rate_op = tf.maximum(
                    cnf.learning_rate_minimum,
                    tf.train.exponential_decay(
                        learning_rate = cnf.learning_rate,
                        global_step   = learning_rate_step,
                        decay_steps   = cnf.learning_rate_decay_step,
                        decay_rate    = cnf.learning_rate_decay,
                        staircase     = True))
            setattr(self, pp(prefix, 'learning_rate_op'), learning_rate_op)
            optim = tf.train.RMSPropOptimizer(
                                learning_rate = learning_rate_op,
                                momentum      = 0.95,
                                epsilon       = 0.01).minimize(loss)
            setattr(self, pp(prefix, 'optim'), optim)
    def send_some_metrics(self, prefix):
        prefix = self.extend_prefix(prefix)
        learning_rate_name = pp(prefix, 'learning_rate')
        learning_rate_op = getattr(self, pp(prefix, 'learning_rate_op'))
        learning_rate_step = getattr(self, pp(prefix, 'learning_rate_step'))
        step = getattr(self, pp(prefix, 'step'))
        
        learning_rate_value = learning_rate_op.eval({learning_rate_step: step})
        setattr(self.m, learning_rate_name, learning_rate_value)
        
        memory_count = getattr(self, pp(prefix, 'memory')).count
        setattr(self.m, pp(prefix, 'memory_size'), memory_count)
        
    def add_dense_layers(self, architecture, input_layer, parameters, name_aux):
        #TODO delete config parameter
        last_layer = input_layer
        #print(last_layer, "as input")
#        prefix = prefix + "_" if prefix != '' else prefix
#        
#        parameters = getattr(self, prefix + 'w')
        histograms = []
        for i, neurons in enumerate(architecture):
            number = 'l' + str(i + 1)
            layer_name = name_aux + number
            layer, weights, biases = \
                utils.linear(input_ = last_layer,
                       output_size = neurons,
                       activation_fn = tf.nn.relu,
                       name = layer_name)
#            histograms += [tf.summary.histogram("w_" + layer_name, weights),
#                           tf.summary.histogram("b_" + layer_name, biases)]
#                           tf.summary.histogram("o_" + layer_name, layer)]
            #setattr(self, layer_name, layer)
            parameters[layer_name + "_w"] = weights
            parameters[layer_name + "_b"] = biases
            last_layer = layer
#            print(layer_name, layer.get_shape().as_list(), 'added')        
            #print(layer, 'added', layer_name)
        return last_layer, histograms

    def create_target(self, config):
        #print("Creating target...")

        prefix = config.prefix + '_' if config.prefix != '' else config.prefix
        #config = config
        #config = self.config
#        # target network
        aux1 = prefix + 'target'                         # mc_target
        aux2 = aux1 + '_s_t'                             # mc_target_s_t
        aux3 = aux1 + '_w'                               # mc_target_w
        aux4 = aux1 + '_q'                               # mc_target_q
        aux5 = 'w' if prefix == '' else prefix + 'w'     # mc_w
        aux6 = aux4 + '_idx'                             # mc_target_q_idx        
        aux7 = aux4 + '_with_idx'                        # mc_target_q_with_idx
        aux8 = prefix + 'outputs_idx'                    # mc_outputs_idx
        target_w = {}
        
        
        setattr(self, aux3, target_w)
        with tf.variable_scope(aux1):
            target_s_t = tf.placeholder("float",
                        [None, config.history_length, self.environment.state_size],
                        name = aux2)
            shape = target_s_t.get_shape().as_list()
            target_s_t_flat = \
                tf.reshape(target_s_t,
                          [-1, reduce(lambda x, y: x * y, shape[1:])])
            if config.prefix == 'c':
                self.c_target_g_t = tf.placeholder("float",
                                   [None, self.ag.goal_size],
                                   name = 'c_target_g_t')
                self.target_gs_t = tf.concat([self.c_target_g_t, target_s_t_flat],
                                   axis = 1,
                                   name = 'c_target_gs_concat')
                last_layer = self.target_gs_t
            else:
                last_layer = target_s_t_flat
                
#            histograms_ = getattr(self, prefix + 'histograms')
            
            last_layer, _ = self.add_dense_layers(architecture = config.architecture,
                                               input_layer = last_layer,
                                               parameters = target_w,
                                               name_aux = '')
#            histograms_ += histograms
            
            
            if self.ag.dueling:
                #print(aux4)
                target_q = self.add_dueling(prefix = aux1, input_layer = last_layer)
            else:
                target_q, weights, biases = \
                            linear(last_layer,
                                   config.q_output_length, name=aux4)  
                getattr(self, aux3)['q_w'] = weights
                getattr(self, aux3)['q_b'] = biases                   
            #print(target_q)
            
            setattr(self, aux2, target_s_t)
            setattr(self, aux4, target_q)
            if self.config.ag.double_q:               
                #Double DQN                  
                target_q_idx = tf.placeholder('int32', [None, None], aux8)
                target_q_with_idx = tf.gather_nd(target_q, target_q_idx)
                setattr(self, aux6, target_q_idx)
                setattr(self, aux7, target_q_with_idx)
    
        #self.show_attrs()
        with tf.variable_scope(prefix + 'pred_to_target'):
            target_w_input = {}
            target_w_assign_op = {}
            w = getattr(self, aux5)
            
            for name in w.keys():
#                print("__________________________")
                target_w_input[name] = tf.placeholder(
                               'float32',
                               target_w[name].get_shape().as_list(),
                               name=name)
                target_w_assign_op[name] = target_w[name].assign(
                                                value = target_w_input[name])
#                print(target_w_input[name])
#                print(target_w_assign_op[name])
        setattr(self, aux3 + "_input", target_w_input)
        setattr(self, aux3 + "_assign_op", target_w_assign_op)
        
        
        
    def save_model(self, step=None):
        if not os.path.exists(self.checkpoints_dir):
            os.makedirs(self.checkpoints_dir)
        self.saver.save(self.sess, self.checkpoints_dir, global_step=step)
        msg = "\nSaved checkpoint step=%d" % (step)#, self.checkpoints_dir)
        print(msg)

    def load_model(self):
        print(" [*] Loading checkpoints...")
        temp = self.config.ag.mode
        self.config.ag.mode = 'train'
        ckpt = tf.train.get_checkpoint_state(self.checkpoints_dir2)
       
        if ckpt and ckpt.model_checkpoint_path:
            ckpt_name = os.path.basename(ckpt.model_checkpoint_path)
            fname = os.path.join(self.checkpoints_dir2, ckpt_name)
            self.saver.restore(self.sess, fname)
            print(" [*] Load SUCCESS: %s" % fname)
            success = True
        else:
            print(" [!] Load FAILED: %s" % self.checkpoints_dir)
            success = False
        self.config.ag.mode = temp
        return success
    
    def delete_last_checkpoints(self):
        try:
            shutil.rmtree(os.path.join(self.config.gl.checkpoints_dir,
                                self.config.model_name))
        except FileNotFoundError:
            pass
        
    def write_configuration(self):
        filename = self.config.model_name + "_" + "cnf.txt"
        filepath = os.path.join(self.logs_dir, filename)
        with open(filepath, 'w') as fp:
            fp.write(self.config.to_str())
    def write_output(self):
        filename = self.config.model_name + "_" + "episodes.txt"
        filepath = os.path.join(self.logs_dir, filename)
        with open(filepath, 'w') as fp:
            fp.write(self.output)
       
    @property
    def checkpoints_dir(self):
        return os.path.join(self.config.gl.checkpoints_dir,
                            self.config.model_name,
                            self.config.model_name)
    @property
    def checkpoints_dir2(self):
        return os.path.join(self.config.gl.checkpoints_dir,
                            self.config.model_name)

    @property
    def logs_dir(self):
        return os.path.join(self.config.gl.logs_dir,
                            self.config.model_name)

   
        
    @property
    def saver(self):
        if self._saver == None:
            self._saver = tf.train.Saver(max_to_keep=10)
        return self._saver




