#!/usr/bin/env python3

"""
This script allows you to manually control the simulator
using the keyboard arrows.
"""

import sys
import argparse
import pyglet
import math
from pyglet.window import key
from pyglet import clock
import numpy as np
import gym
import gym_miniworld

import torch
from experiments.pos_delta import Model
from experiments.utils import make_var

parser = argparse.ArgumentParser()
parser.add_argument('--env-name', default='MiniWorld-SimToRealOdo-v0')
parser.add_argument('--domain-rand', action='store_true', help='enable domain randomization')
parser.add_argument('--no-time-limit', action='store_true', help='ignore time step limits')
args = parser.parse_args()

env = gym.make(args.env_name)

if args.no_time_limit:
    env.max_episode_steps = math.inf
if args.domain_rand:
    env.domain_rand = True

def reset_env():
    global prev_obs
    global prev_pos
    global prev_dir
    global prev_dv
    global prev_rv
    prev_obs = env.reset()
    prev_pos = env.agent.pos
    prev_dir = env.agent.dir
    prev_dv = env.agent.dir_vec
    prev_rv = env.agent.right_vec

reset_env()

# Create the display window
env.render('pyglet')

model = Model()
model.load_state_dict(torch.load('pos_delta_model.torch'))
model.eval()
model.cuda()

def step(action):
    global prev_obs
    global prev_pos
    global prev_dir
    global prev_dv
    global prev_rv

    print('step {}: {}'.format(env.step_count, env.actions(action).name))

    obs, reward, done, info = env.step(action)

    obs0 = make_var(prev_obs.transpose(2, 1, 0)).unsqueeze(0)
    obs1 = make_var(obs.transpose(2, 1, 0)).unsqueeze(0)
    posd = model(obs0, obs1)
    posd = posd.squeeze().cpu().detach().numpy()

    delta_dir = env.agent.dir - prev_dir
    delta_dv = np.dot(env.agent.pos - prev_pos, prev_dv)
    delta_rv = np.dot(env.agent.pos - prev_pos, prev_rv)

    print('{:+.3f} {:+.3f} {:+.3f}'.format(*posd))
    print('{:+.3f} {:+.3f} {:+.3f}'.format(delta_dv, delta_rv, delta_dir))
    print()

    prev_obs = obs
    prev_pos = env.agent.pos
    prev_dir = env.agent.dir
    prev_dv = env.agent.dir_vec
    prev_rv = env.agent.right_vec

    if done:
        print('done! reward={:.2f}'.format(reward))
        reset_env()

    env.render('pyglet')

@env.unwrapped.window.event
def on_key_press(symbol, modifiers):
    """
    This handler processes keyboard commands that
    control the simulation
    """

    if symbol == key.BACKSPACE or symbol == key.SLASH:
        print('RESET')
        reset_env()
        env.render('pyglet')
        return

    if symbol == key.ESCAPE:
        env.close()
        sys.exit(0)

    if symbol == key.UP:
        step(env.actions.move_forward)
    elif symbol == key.DOWN:
        step(env.actions.move_back)

    elif symbol == key.LEFT:
        step(env.actions.turn_left)
    elif symbol == key.RIGHT:
        step(env.actions.turn_right)

    elif symbol == key.PAGEUP or symbol == key.P:
        step(env.actions.pickup)
    elif symbol == key.PAGEDOWN or symbol == key.D:
        step(env.actions.drop)

@env.unwrapped.window.event
def on_key_release(symbol, modifiers):
    pass

@env.unwrapped.window.event
def on_draw():
    env.render('pyglet')

@env.unwrapped.window.event
def on_close():
    pyglet.app.exit()

# Enter main event loop
pyglet.app.run()

env.close()
