from __future__ import print_function
import os
import time
import random
import numpy as np
from tqdm import tqdm
from functools import reduce
import tensorflow as tf
import sys

from base import Agent, Epsilon
from history import History
from replay_memory import ReplayMemory
from ops import linear, clipped_error
from utils import get_time, save_pkl, load_pkl
from goals import MDPGoal
from metrics import Metrics
from configuration import Constants as CT

        
class HDQNAgent(Agent):
    def __init__(self, config, environment, sess):
        super().__init__(config)
        self.sess = sess
        self.weight_dir = 'weights'

        self.config = config
        self.ag = self.config.ag
        self.c = self.ag.c
        self.mc = self.ag.mc
        self.gl = self.config.gl
        #print(self.mc)
        self.environment = environment
        self.goals = self.define_goals()
        
        self.mc.update({"q_output_length" : self.ag.goal_size}, add = True)
        self.c.update({"q_output_length" : self.environment.action_size}, add = True)
        
  
        
        self.mc_history = History(length_ = self.mc.history_length,
                                  size    = self.environment.state_size)
        
        self.c_history = History(length_ = self.c.history_length,
                                 size    = self.environment.state_size)
        
        self.mc_memory = ReplayMemory(config      = self.mc,
                                      model_dir  = self.model_dir,
                                      screen_size = self.environment.state_size)
        self.c_memory = ReplayMemory(config      = self.c,
                                      model_dir  = self.model_dir,
                                      screen_size = self.environment.state_size + \
                                      self.ag.goal_size)

        
            
        self.m = Metrics(self.config, self.goals)
        
        self.config.print()
        self.build_hdqn()
    
    
    def aux(self, screen):
        #Auxiliary function
        return self.environment.gym.one_hot_inverse(screen)

    def get_goal(self, n):
        return self.goals[n]
        
    def define_goals(self):
        
        self.ag.goal_size = self.environment.state_size
        
        
        goals = {}
        for n in range(self.ag.goal_size):
            if self.environment.env_name in CT.MDP_envs:
                goal_name = "g" + str(n)
                goal = MDPGoal(n, goal_name, self.c)            
                goal.setup_one_hot(self.ag.goal_size)
            elif 0:
                #Space Fortress
                pass
            else:
                raise ValueError("No prior goals for " + self.environment.env_name)
            goals[goal.n] = goal
        
        return goals
    
    def set_next_goal(self, test_ep = None):
        
        ep = test_ep or self.mc_epsilon.steps_value(self.mc_step)
        self.m.update_epsilon(goal_name = None, value = ep)
        if random.random() < ep or self.gl.randomize:
            n_goal = random.randrange(self.ag.goal_size)
        else:
            screens = self.mc_history.get()
            n_goal = self.mc_q_goal.eval({self.mc_s_t: [screens]})[0]
#        n_goal = 5
        self.m.mc_goals.append(n_goal)
        goal = self.get_goal(n_goal)
        goal.set_counter += 1
        self.current_goal = goal
        
    def predict_next_action(self, test_ep = None):
        
        
        
        #s_t should have goals and screens concatenated
        ep = test_ep or self.current_goal.epsilon
        
        self.m.update_epsilon(goal_name = self.current_goal.name, value = ep)
        
        if random.random() < ep or self.gl.randomize:
            action = random.randrange(self.environment.action_size)
            
        else:
            screens = self.c_history.get()
            
            action = self.c_q_action.eval(
                            {self.c_s_t: [screens],
                             self.c_g_t: [self.current_goal.one_hot]})[0]
#        action = int(self.aux(self.c_history.get()[-1]) < self.current_goal.n)
#        print('**',self.aux(self.c_history.get()[-1]), self.current_goal.n, action)
        self.m.c_actions.append(action)
        return action
    def mc_observe(self, screen, ext_reward, goal_n, terminal):
        if self.display_episode:
            pass#print("MC ", ext_reward, "while", self.aux(screen), "g:", goal_n)
        
        self.mc_history.add(screen)
        next_state = screen
        self.mc_memory.add(next_state, ext_reward, goal_n, terminal)

        if self.mc_step >  self.mc.learn_start:
            if self.mc_step % self.mc.train_frequency == 0:
                self.mc_q_learning_mini_batch()

            if self.mc_step % self.mc.target_q_update_step ==\
                        self.mc.target_q_update_step - 1:
                self.mc_update_target_q_network()    
    
    def c_observe(self, screen, int_reward, action, terminal):
        if self.display_episode:
            pass#print("C ", int_reward, "while", self.aux(screen), "a:", action)
       
        self.c_history.add(screen)
        next_state = np.hstack([self.current_goal.one_hot, screen])

        self.c_memory.add(next_state, int_reward, action, terminal)
        
        if self.c_step > self.c.learn_start:
            if self.c_step % self.c.train_frequency == 0:
                self.c_q_learning_mini_batch()

            if self.c_step % self.c.target_q_update_step == self.c.target_q_update_step - 1:
                self.c_update_target_q_network()

    def mc_q_learning_mini_batch(self):
        if self.mc_memory.count < self.mc_history.length:
            return
        
        if self.a == False:
            print("MC at ", self.c_step)
            self.a = True
        s_t, goal, ext_reward, s_t_plus_1, terminal = self.mc_memory.sample()
        
        q_t_plus_1 = self.mc_target_q.eval({self.mc_target_s_t: s_t_plus_1})

        terminal = np.array(terminal) + 0.
        max_q_t_plus_1 = np.max(q_t_plus_1, axis=1)
        target_q_t = (1. - terminal) * self.mc.discount * max_q_t_plus_1 + ext_reward
        
        #print("SAAAAAMPLING")
#        for s,g,r,s1,t in zip(s_t, goal, ext_reward, s_t_plus_1, terminal):
#            if r == 0:
#                continue
#            print("******")
#            print("s_t\n",s[-1])
#            print("g",g)
#            print("s_t1\n",s1[-1])
#            print("r",r)
#            print("t",t)
        
        _, q_t, loss, summary_str = self.sess.run([self.mc_optim, self.mc_q,
                                             self.mc_loss, self.mc_q_summary], {
            self.mc_target_q_t: target_q_t,
            self.mc_action: goal,
            self.mc_s_t: s_t,
            self.mc_learning_rate_step: self.mc_step,
        })
        self.writer.add_summary(summary_str, self.mc_step)
    
        self.m.mc_add_update(loss, q_t.mean())
        

    def c_q_learning_mini_batch(self):
        if self.c_memory.count < self.c_history.length:
            return
        
        
        if self.b == False:
            print("C at ", self.c_step)
            self.b = True
        s_t, action, int_reward, s_t_plus_1, terminal = self.c_memory.sample()
        
        #TODO: optimize goals in memory
        g_t = np.vstack([g[0] for g in s_t[:, :, :self.ag.goal_size]]) 
        s_t = s_t[:, :, self.ag.goal_size:]
        
        
        g_t_plus_1 = np.vstack([g[0] for g in s_t[:, :, :self.ag.goal_size]])
        s_t_plus_1 = s_t_plus_1[:, :, self.ag.goal_size:]
        
        
        for s,a,r,s1,t,g,g1 in zip(s_t, action, int_reward, s_t_plus_1, terminal,\
                        g_t, g_t_plus_1):
            break
            if r == 0:
                continue
            print("******")
            print("s_t\n",s[-1])
            print("g_t",g)
            print("a",a)
            print("s_t1\n",s1[-1])
            print("g_t1",g1)
            print("r",r)
            print("t",t)
        
        q_t_plus_1 = self.c_target_q.eval({
                                    self.c_target_s_t: s_t_plus_1,
                                    self.c_target_g_t: g_t_plus_1,
                                     })
        
        terminal = np.array(terminal) + 0. #Boolean to float
    
        max_q_t_plus_1 = np.max(q_t_plus_1, axis=1)
        target_q_t = (1. - terminal) * self.c.discount * max_q_t_plus_1 + int_reward

        _, q_t, loss, summary_str = self.sess.run([self.c_optim, self.c_q,
                                             self.c_loss, self.c_q_summary], {
            self.c_target_q_t: target_q_t,
            self.c_action: action,
            self.c_s_t: s_t,
            self.c_g_t: g_t,
            self.c_learning_rate_step: self.c_step,
        })
        self.writer.add_summary(summary_str, self.c_step)
        self.m.c_add_update(loss, q_t.mean())


    
    def new_episode(self):
        #screen, reward, action, terminal = self.environment.new_random_game()
        screen, _, _, _ = self.environment.new_game(False)        
        self.mc_history.fill_up(screen)
        self.c_history.fill_up(screen)
        self.display_episode = random.random() < self.gl.display_prob
      
        return 
    
    def train(self):
        self.a, self.b = False, False
        
        
        
        mc_start_step = 0
        c_start_step = 0
        
        self.mc_epsilon = Epsilon(self.mc, mc_start_step)
        for key, goal in self.goals.items():
            goal.setup_epsilon(self.c, c_start_step) #TODO load individual
        
        self.new_episode()
            
        self.m.start_timer()
        # Initial goal
        self.mc_step = mc_start_step
        self.set_next_goal()
        
        if self.gl.display_prob < .011:            
            iterator = tqdm(range(c_start_step, self.c.max_step),
                                              ncols=70, initial=c_start_step)
        else:
            iterator = range(c_start_step, self.c.max_step)
        for self.c_step in iterator:
            if self.c_step == self.c.learn_start:                
                self.m.restart()
            
            # Controller acts
            action = self.predict_next_action()
            if self.display_episode:
                print('s:',self.aux(self.c_history.get()[-1]),', g:',self.current_goal.n,', a:', action)
                
            screen, ext_reward, terminal = self.environment.act(action, is_training = True)            
            self.m.add_act(action, self.environment.gym.one_hot_inverse(screen))
            
            
                        
            
            # Controller learns
#            if self.config.display:
#                
#                print('s', screen)
#                print('g', self.current_goal.one_hot)
            goal_achieved = self.current_goal.is_achieved(screen)
            int_reward = 1. if goal_achieved else 0.
            
            self.c_observe(screen, int_reward, action, terminal)

            
            self.m.increment_rewards(int_reward, ext_reward)
            
            if terminal or goal_achieved:
                
                self.current_goal.finished(self.m, goal_achieved)
                # Meta-controller learns                
                self.mc_observe(screen, self.m.mc_step_reward,
                                                self.current_goal.n, terminal)
                success = self.m.mc_step_reward == 1
                self.m.mc_step_reward = 0    
                if goal_achieved and self.display_episode:
                    pass#print("Achieved!!!", self.current_goal.n)
                if terminal:
                    if self.display_episode:
                        print(self.aux(screen), success)
                        
                    self.m.close_episode()
                    self.new_episode()
                    
#                print("This", self.m.mc_step_reward)
                    
                self.mc_step += 1
                
                # Meta-controller sets goal
                self.set_next_goal()
                self.m.mc_goals.append(self.current_goal.n)
                
                
#            print('c', self.m.c_update_count, self.c_step)
#            print('mc', self.m.mc_update_count, self.mc_step)
            if self.display_episode:
                pass#print("ext",ext_reward,', int',int_reward)
            if terminal and self.display_episode:
                print("__________________________") 
            
            
            if self.c_step < self.c.learn_start:
                continue
            if self.c_step % self.c.test_step != self.c.test_step - 1:
                continue
            #assert self.m.mc_update_count > 0, "MC hasn't been updated yet"
            #assert not (terminal and self.m.mc_ep_reward == 0.)
            self.m.compute_test('c', self.m.c_update_count)
            self.m.compute_test('mc', self.m.mc_update_count)
            
            self.m.compute_goal_results(self.goals)
            self.m.compute_state_visits()
            
            self.m.print('mc')
            self.m.c_print()
            
            
            if self.m.has_improved(prefix = 'mc'):
                self.c_step_assign_op.eval(
                        {self.c_step_input: self.c_step + 1})
                self.mc_step_assign_op.eval(
                        {self.mc_step_input: self.mc_step + 1})
                self.save_model(self.c_step + 1)
                self.save_model(self.mc_step + 1)
                self.m.update_best_score()
                

            if self.c_step > 50:
                self.send_learning_rate_to_metrics()
                summary = self.m.get_summary()
                self.m.filter_summary(summary)
                self.inject_summary(summary, self.c_step)

            self.m.restart()
            
    def send_learning_rate_to_metrics(self):
        self.m.mc_learning_rate = self.mc_learning_rate_op.eval(
                                {self.mc_learning_rate_step: self.mc_step})
        self.m.c_learning_rate = self.c_learning_rate_op.eval(
                                {self.c_learning_rate_step: self.c_step})
        

        
    def build_meta_controller(self):
        self.mc_w = {}
        self.mc_target_w = {}
        # training meta-controller network
        with tf.variable_scope('mc_prediction'):
            # tf Graph input
            self.mc_s_t = tf.placeholder("float",
                        [None, self.mc_history.length, self.environment.state_size],
                        name='mc_s_t')
            print(self.mc_s_t)
            shape = self.mc_s_t.get_shape().as_list()
            self.mc_s_t_flat = tf.reshape(self.mc_s_t, [-1, reduce(
                                            lambda x, y: x * y, shape[1:])])            
            
            last_layer = self.mc_s_t_flat
            last_layer = self.add_dense_layers(config = self.mc,
                                               input_layer = last_layer,
                                               prefix = 'mc')
            self.mc_q, self.mc_w['q_w'], self.mc_w['q_b'] = linear(last_layer,
                                                  self.ag.goal_size,
                                                  name='mc_q')
            self.mc_q_goal= tf.argmax(self.mc_q, axis=1)
            
            q_summary = []
            avg_q = tf.reduce_mean(self.mc_q, 0)
            

            for idx in range(self.mc.q_output_length):
                q_summary.append(tf.summary.histogram('mc_q/%s' % idx, avg_q[idx]))
            self.mc_q_summary = tf.summary.merge(q_summary, 'mc_q_summary')

        # target network
        self.create_target(config = self.mc)

        #Meta Controller optimizer
        with tf.variable_scope('mc_optimizer'):
            self.mc_target_q_t = tf.placeholder('float32', [None],
                                               name='mc_target_q_t')
            self.mc_action = tf.placeholder('int64', [None], name='mc_action')

            mc_action_one_hot = tf.one_hot(self.mc_action, self.ag.goal_size,
                                       1.0, 0.0, name = 'mc_action_one_hot')
            mc_q_acted = tf.reduce_sum(self.mc_q * mc_action_one_hot,
                                   reduction_indices = 1, name = 'mc_q_acted')

            mc_delta = self.mc_target_q_t - mc_q_acted

            #self.global_step = tf.Variable(0, trainable=False)

            self.mc_loss = tf.reduce_mean(clipped_error(mc_delta),
                                         name = 'mc_loss')
            self.mc_learning_rate_step = tf.placeholder('int64', None,
                                            name='mc_learning_rate_step')
            self.mc_learning_rate_op = tf.maximum(
                    self.mc.learning_rate_minimum,
                    tf.train.exponential_decay(
                        learning_rate = self.mc.learning_rate,
                        global_step   = self.mc_learning_rate_step,
                        decay_steps   = self.mc.learning_rate_decay_step,
                        decay_rate    = self.mc.learning_rate_decay,
                        staircase     = True))
            self.mc_optim = tf.train.RMSPropOptimizer(
                                learning_rate = self.mc_learning_rate_op,
                                momentum      = 0.95,
                                epsilon       = 0.01).minimize(self.mc_loss)

    def build_controller(self):
        self.c_w = {}
        self.c_target_w = {}
    
        with tf.variable_scope('c_prediction'):
            #input_size = self.environment.state_size + self.ag.goal_size
            self.c_s_t = tf.placeholder("float",
                                [None, self.c_history.length, self.environment.state_size],
                                name = 'c_s_t')
            shape = self.c_s_t.get_shape().as_list()
            self.c_s_t_flat = tf.reshape(self.c_s_t, [-1, reduce(
                    lambda x, y: x * y, shape[1:])])
            self.c_g_t = tf.placeholder("float",
                               [None, self.ag.goal_size],
                               name = 'c_g_t')
            self.c_gs_t = tf.concat([self.c_g_t, self.c_s_t_flat],
                           axis = 1,
                           name = 'c_gs_concat')
            print(self.c_g_t)
            print(self.c_s_t_flat)
            last_layer = self.c_gs_t
            print(last_layer)
            last_layer = self.add_dense_layers(config = self.c,
                                               input_layer = last_layer,
                                               prefix = 'c')
            self.c_q, self.c_w['q_w'], self.c_w['q_b'] = linear(last_layer,
                                                  self.environment.action_size,
                                                  name='c_q')
            print(self.c_q)
            self.c_q_action= tf.argmax(self.c_q, axis=1)
            
            q_summary = []
            avg_q = tf.reduce_mean(self.c_q, 0)
            

            for idx in range(self.c.q_output_length):
                q_summary.append(tf.summary.histogram('c_q/%s' % idx, avg_q[idx]))
            self.c_q_summary = tf.summary.merge(q_summary, 'c_q_summary')

        # target network
        self.create_target(self.c)
        
        
        #Controller optimizer
        with tf.variable_scope('c_optimizer'):
            self.c_target_q_t = tf.placeholder('float32', [None],
                                               name='c_target_q_t')
            self.c_action = tf.placeholder('int64', [None], name='c_action')

            c_action_one_hot = tf.one_hot(self.c_action, self.environment.action_size,
                                       1.0, 0.0, name = 'c_action_one_hot')
            c_q_acted = tf.reduce_sum(self.c_q * c_action_one_hot,
                                   reduction_indices = 1, name = 'c_q_acted')

            c_delta = self.c_target_q_t - c_q_acted

            #self.global_step = tf.Variable(0, trainable=False)

            self.c_loss = tf.reduce_mean(clipped_error(c_delta),
                                         name = 'c_loss')
            self.c_learning_rate_step = tf.placeholder('int64', None,
                                            name='c_learning_rate_step')
            self.c_learning_rate_op = tf.maximum(
                    self.c.learning_rate_minimum,
                    tf.train.exponential_decay(
                        learning_rate = self.c.learning_rate,
                        global_step   = self.c_learning_rate_step,
                        decay_steps   = self.c.learning_rate_decay_step,
                        decay_rate    = self.c.learning_rate_decay,
                        staircase     = True))
            self.c_optim = tf.train.RMSPropOptimizer(
                                learning_rate = self.c_learning_rate_op,
                                momentum      = 0.95,
                                epsilon       = 0.01).minimize(self.c_loss)
    def build_hdqn(self):

        
        with tf.variable_scope('c_step'):
            self.c_step_op = tf.Variable(0, trainable=False, name='c_step')
            self.c_step_input = tf.placeholder('int32', None,
                                                  name='c_step_input')
            self.c_step_assign_op = \
                        self.c_step_op.assign(self.c_step_input)
            
        with tf.variable_scope('mc_step'):
            self.mc_step_op = tf.Variable(0, trainable=False,
                                            name='mc_step')
            self.mc_step_input = tf.placeholder('int32', None,
                                           name='mc_step_input')
            self.mc_step_assign_op = \
                        self.mc_step_op.assign(self.mc_step_input)
                
        
        print("Building meta-controller")
        self.build_meta_controller()
        print("Building controller")
        
        self.build_controller()
        
        self.setup_summary(self.m.scalar_tags, self.m.histogram_tags)
            
        tf.global_variables_initializer().run()
        
        mc_vars = list(self.mc_w.values()) + [self.mc_step_op]
        c_vars = list(self.c_w.values()) + [self.c_step_op]
        
        
        self._saver = tf.train.Saver(var_list = mc_vars + c_vars,
                                      max_to_keep=30)

        self.load_model()
        self.mc_update_target_q_network()
        self.c_update_target_q_network()
        
    # def setup_summary(self):
                
        # super().setup_summary(self.m.scalar_tags, self.m.histogram_tags)
        # self.writer = tf.summary.FileWriter('./logs/%s' % \
                                          # self.model_dir, self.sess.graph)
        
    def mc_update_target_q_network(self):    
        for name in self.mc_w.keys():
            self.mc_target_w_assign_op[name].eval(
                    {self.mc_target_w_input[name]: self.mc_w[name].eval()})
            
    def c_update_target_q_network(self):
        for name in self.c_w.keys():
            self.c_target_w_assign_op[name].eval(
                    {self.c_target_w_input[name]: self.c_w[name].eval()})
    

    def save_weight_to_pkl(self):
        if not os.path.exists(self.weight_dir):
            os.makedirs(self.weight_dir)

        for name in self.w.keys():
            save_pkl(obj = self.w[name].eval(),
                    path = os.path.join(self.weight_dir, "%s.pkl" % name))

    def load_weight_from_pkl(self, cpu_mode=False):
        with tf.variable_scope('load_pred_from_pkl'):
            self.w_input = {}
            self.w_assign_op = {}

            for name in self.w.keys():
                self.w_input[name] = tf.placeholder('float32',
                                        self.w[name].get_shape().as_list(),
                                        name=name)
                self.w_assign_op[name] = self.w[name].assign(self.w_input[name])

        for name in self.w.keys():
            self.w_assign_op[name].eval(
                    {self.w_input[name]: load_pkl(os.path.join(
                                        self.weight_dir, "%s.pkl" % name))})

        self.update_target_q_network()
