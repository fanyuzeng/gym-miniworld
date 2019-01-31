#!/usr/bin/env python3

import time
import random
import argparse
import math
import json
from functools import reduce
import operator

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.autograd import Variable

import gym
import gym_miniworld

from .utils import *

class Model(nn.Module):
    def __init__(self):
        super().__init__()

        self.obs_to_enc = nn.Sequential(
            nn.Conv2d(3, 64, kernel_size=5, stride=2),
            nn.BatchNorm2d(64),
            nn.LeakyReLU(),

            nn.Conv2d(64, 64, kernel_size=5, stride=2),
            nn.BatchNorm2d(64),
            nn.LeakyReLU(),

            nn.Conv2d(64, 64, kernel_size=4, stride=2),
            nn.BatchNorm2d(64),
            nn.LeakyReLU(),

            #Print(),
            Flatten(),

            nn.Linear(2240, 512),
            nn.LeakyReLU(),
        )

        self.enc_to_delta = nn.Sequential(
            nn.Linear(2 * 512, 512),
            nn.LeakyReLU(),
            nn.Linear(512, 512),
            nn.LeakyReLU(),
            nn.Linear(512, 3),
        )

        self.apply(init_weights)

    def forward(self, obs0, obs1):
        obs0 = obs0 / 255
        obs1 = obs1 / 255

        obs0_enc = self.obs_to_enc(obs0)
        obs1_enc = self.obs_to_enc(obs1)

        enc = torch.cat((obs0_enc, obs1_enc), dim=1)
        #print(enc.size())

        pos_delta = self.enc_to_delta(enc)

        return pos_delta

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", default=256, type=int)
    parser.add_argument("--buffer-size", default=16384, type=int)
    parser.add_argument("--env", default="MiniWorld-SimToRealOdo-v0")
    args = parser.parse_args()

    env = gym.make(args.env)

    num_actions = env.action_space.n
    print('num actions:', num_actions)

    max_steps = env.max_episode_steps
    print('max episode steps:', max_steps)

    map_shape = (3, 200, 200)
    num_trans = 0
    cur_idx = 0

    # Done indicates that we become done after the current step
    buf_obs0 = np.zeros(shape=(args.buffer_size, 3, 80, 60), dtype=np.uint8)
    buf_obs1 = np.zeros(shape=(args.buffer_size, 3, 80, 60), dtype=np.uint8)
    buf_posd = np.zeros(shape=(args.buffer_size, 3), dtype=np.float32)

    model = Model()
    model.cuda()
    print_model_info(model)

    optimizer = optim.Adam(model.parameters(), lr=1e-4)

    def gen_data(num_episodes=1):
        global cur_idx, num_trans

        for i in range(num_episodes):
            #print(i)

            obs = env.reset()
            obs = obs.transpose(2, 1, 0)

            cur_action = None
            steps_left = 0

            # Initial overhead map
            map = make_var(np.zeros(shape=map_shape)).unsqueeze(0)

            for step_idx in range(max_steps):
                # Pick a random transition index. Prioritize expanding the set.
                if num_trans < args.buffer_size and np.random.uniform(0, 1) < 0.5:
                    cur_idx = num_trans
                else:
                    cur_idx = np.random.randint(0, num_trans + 1) % args.buffer_size
                num_trans = max(num_trans, cur_idx+1)

                # Repeat turn_left, turn_right or move_forward for N steps
                if steps_left == 0:
                    cur_action = np.random.choice([
                        env.actions.turn_left,
                        env.actions.turn_right,
                        env.actions.move_forward,
                        env.actions.move_back
                    ])
                    steps_left = np.random.randint(1, 17)

                buf_obs0[cur_idx] = obs

                pos0 = env.agent.pos
                dir0 = env.agent.dir
                dir_vec = env.agent.dir_vec
                right_vec = env.agent.right_vec

                obs, reward, done, info = env.step(cur_action)
                obs = obs.transpose(2, 1, 0)
                steps_left -= 1

                buf_obs1[cur_idx] = obs

                pos1 = env.agent.pos
                dir1 = env.agent.dir
                buf_posd[cur_idx] = [
                    np.dot(pos1 - pos0, dir_vec),
                    np.dot(pos1 - pos0, right_vec),
                    dir1 - dir0
                ]

                if done:
                    break

    while num_trans <= args.batch_size:
        gen_data()

    running_loss = None

    for i in range(5000000):
        print('batch #{} (num trans={})'.format(i+1, num_trans))

        batch_idx = np.random.randint(0, num_trans - args.batch_size)
        batch_obs0 = make_var(buf_obs0[batch_idx:(batch_idx+args.batch_size)])
        batch_obs1 = make_var(buf_obs1[batch_idx:(batch_idx+args.batch_size)])
        batch_posd = make_var(buf_posd[batch_idx:(batch_idx+args.batch_size)])

        pred_posd = model(batch_obs0, batch_obs1)

        # Generate data while the GPU is computing
        gen_data()

        # Compute an L2 loss
        # Rescale the position loss so the magnitude is similar to the rotation loss
        dp = 10 * (pred_posd[:, 0:2] - batch_posd[:, 0:2])
        dd = pred_posd[:, 2] - batch_posd[:, 2]
        loss = (dp * dp).mean() + (dd * dd).mean() # L2 loss

        #diff = pred_posd - batch_posd
        #loss = (diff * diff).mean() # L2 loss

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        if i == 0:
            running_loss = loss.data.item()
        else:
            running_loss = 0.99 * running_loss + 0.01 * loss.data.item()

        print('frames: {}'.format((i+1) * args.batch_size))
        print('running loss: {:.5f}'.format(running_loss))

        if i % 100 == 0:
            print('saving model')
            torch.save(model.state_dict(), 'pos_delta_model.torch')
