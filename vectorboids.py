#!/usr/bin/env python3
from random import randint
import pygame as pg
import torch
import numpy as np
'''
PyNBoids - a Boids simulation - github.com/Nikorasu/PyNBoids
Uses numpy array math instead of math lib, more efficient.
Copyright (c) 2021  Nikolaus Stromberg  nikorasu85@gmail.com
'''
FLLSCRN = True  # True for Fullscreen, or False for Window
WRAP = True  # False avoids edges, True wraps to other side
FISH = False  # True to turn boids into fish
WIDTH = 1200  # Window Width (1200)
HEIGHT = 800  # Window Height (800)
BGCOLOR = (0, 0, 0)  # Background color in RGB
SHOWFPS = True  # show frame rate

SEPSIZE = 20
bonus_factor = 1

DEBUG = False
if DEBUG:
    SPEED = 0  # Movement speed
    FPS = 15  # 30-90
    BOIDZ = 150
    NEIGHBSIZE = 80
else:
    SPEED = 150
    FPS = 60
    BOIDZ = 300
    NEIGHBSIZE = 60


class Boid(pg.sprite.Sprite):

    def __init__(self, boidNum, data, drawSurf, isFish=False, cHSV=None):
        super().__init__()
        self.data = data
        self.bnum = boidNum
        self.drawSurf = drawSurf
        self.image = pg.Surface((15, 15)).convert()
        self.image.set_colorkey(0)
        self.color = pg.Color(0)  # preps color so we can use hsva
        self.color.hsva = (
            randint(0, 360), 25,
            100) if cHSV is None else cHSV  # randint(5,55) #4goldfish
        if isFish:  # (randint(120,300) + 180) % 360  #4noblues
            pg.draw.polygon(self.image,
                            self.color, ((7, 0), (12, 5), (3, 14), (11, 14),
                                         (2, 5), (7, 0)),
                            width=3)
            self.image = pg.transform.scale(self.image, (16, 24))
        else:
            pg.draw.polygon(self.image, self.color,
                            ((7, 0), (13, 14), (7, 11), (1, 14), (7, 0)))
        self.neighbSize = NEIGHBSIZE
        self.sepSize = SEPSIZE
        self.orig_image = pg.transform.rotate(self.image.copy(), -90)
        self.dir = pg.Vector2(1, 0)  # sets up forward direction
        maxW, maxH = self.drawSurf.get_size()
        self.rect = self.image.get_rect(center=(randint(50, maxW - 50),
                                                randint(50, maxH - 50)))
        self.ang = randint(0, 360)  # random start angle, & position ^
        self.pos = pg.Vector2(self.rect.center)
        self.data.array[self.bnum, :3] = torch.tensor(
            [self.pos[0], self.pos[1], self.ang])
        self.data.forces[self.bnum] = (2 * torch.rand((2, ))) - 1
        self.data.boidz[self.bnum] = self

    def draw_delta(self, delta):
        pg.draw.line(self.drawSurf,
                     self.color,
                     self.pos,
                     pg.Vector2(self.pos[0] + delta[0],
                                self.pos[1] + delta[1]),
                     width=1)

    def draw_to(self, pos):
        pg.draw.line(self.drawSurf,
                     self.color,
                     self.pos,
                     pg.Vector2(pos[0], pos[1]),
                     width=1)

    def average_force(self, force, affect_count):
        force_avg = force.sum(axis=1) / affect_count
        # If there are no neighbors, we will divide by 0 (resulting in nan).
        # Replace those with 0.0 so that we have no cohere force.
        return torch.nan_to_num(force_avg, nan=0.0)

    def deltas(self, positions):
        deltas = positions.unsqueeze(0) - positions.unsqueeze(1)
        dists = torch.linalg.norm(deltas, axis=-1) + 1e-6

        return deltas, dists

    def see_mask(self,
                 forces,
                 deltas,
                 dists,
                 size,
                 use_vision=True):
        isNeighb = dists < size

        # We should not be our own neighbor
        self_attn = 1 - torch.eye(len(deltas))
        isNeighb = isNeighb * self_attn

        # Without vision, large flocks thats collide tend to merge
        # Whereas with vision, large flocks have some collective momentum
        if use_vision:
            cos_sim = torch.nn.functional.cosine_similarity(deltas,forces.unsqueeze(1),
                                                            dim=-1)
            # 180 degree vision
            canSee = (cos_sim > 0)
            isNeighb = isNeighb * canSee

        # for j in range(len(self.data.boidz)):
        #     if canSee[0,j]:
        #         self.draw_delta(deltas[0,j])
        # self.draw_delta(forces[0]*10000000)


        return isNeighb

    def do_separate_v(self, forces, deltas, dists, debug=False):
        shouldSep = self.see_mask(forces, deltas, dists,
                                  self.sepSize, use_vision=False).unsqueeze(-1)
        dists = dists.unsqueeze(-1)

        normdeltas = deltas / dists
        inverse_negative = dists - self.sepSize

        neighb_deltas = deltas * shouldSep
        # neighb_deltas points from the boid's position towards all neighbors,
        # subtracting that value results in a repulsion
        # that is stronger for nearer neighbors.
        negative_deltas = neighb_deltas * inverse_negative

        affect_count = shouldSep.sum(axis=0)
        away_from_neighb = self.average_force(negative_deltas, affect_count)

        if debug:
            i = 0
            for j in range(len(self.data.boidz)):
                if shouldSep[i, j]:
                    self.draw_delta(negative_deltas[i, j])
                    self.draw_delta(neighb_deltas[i, j])

            for x, b in enumerate(self.data.boidz):
                if affect_count[x]:
                    b.draw_delta(away_from_neighb[x])

        return self.clamp_norm(away_from_neighb)

    def do_cohere_v(self, forces, deltas, dists, debug=False):
        isNeighb = self.see_mask(forces, deltas, dists,
                                 self.neighbSize).unsqueeze(-1)
        neighb_deltas = deltas * isNeighb

        affect_count = isNeighb.sum(axis=0)
        to_neighb_center = self.average_force(neighb_deltas, affect_count)

        if debug:
            i = 0
            for j in range(len(self.data.boidz)):
                if isNeighb[i, j]:
                    self.draw_delta(neighb_deltas[i, j])

            for x, b in enumerate(self.data.boidz):
                if affect_count[x]:
                    b.draw_delta(to_neighb_center[x])

        return self.clamp_norm(to_neighb_center)

    def do_align_v(self, forces, deltas, dists, debug=False):
        isNeighb = self.see_mask(forces, deltas, dists,
                                 self.neighbSize).unsqueeze(-1)

        neighb_forces = forces * isNeighb
        affect_count = isNeighb.sum(axis=0)
        total_forces = self.average_force(neighb_forces, affect_count)

        if debug:
            i = 0
            for j in range(len(self.data.boidz)):
                if isNeighb[i, j]:
                    self.draw_delta(neighb_forces[i, j] * 100)

            for x, b in enumerate(self.data.boidz):
                if affect_count[x]:
                    b.draw_delta(total_forces[x] * 100)

        return self.clamp_norm(total_forces)

    def clamp_norm(self,force):
        norms = torch.linalg.norm(force,dim=-1,keepdim=True)
        f_norm = torch.nan_to_num(force/norms,nan=0)
        clamped_norm = torch.clamp(norms,min=0,max=1)
        return f_norm * clamped_norm

    def update(self, dt, speed, ejWrap=False):
        if self.bnum != 0:
            return

        positions, forces = self.data.array[:, :2], self.data.forces

        deltas, dists = self.deltas(positions)

        sepforce = self.do_separate_v(forces, deltas, dists)
        cohforce = self.do_cohere_v(forces, deltas, dists)
        aliforce = self.do_align_v(forces, deltas, dists)

        # For moments where 
        acceleration = self.clamp_norm(20 * sepforce + 2 * cohforce + 10*aliforce)

        # allforce = torch.nn.functional.normalize(allforce,dim=-1)
        forces = torch.nn.functional.normalize(forces + 10*dt*acceleration)
        
        positions += forces * dt * speed

        angles = torch.rad2deg(torch.atan2(forces[:, 1], forces[:, 0]))

        maxW, maxH = self.drawSurf.get_size()
        # Wrap x
        positions[:, 0] = positions[:, 0] % maxW
        # Wrap y
        positions[:, 1] = positions[:, 1] % maxH

        self.data.array[:, :2] = positions
        self.data.array[:, 2] = angles
        self.data.forces = forces

        # Update data
        for i, b in enumerate(self.data.boidz):
            b.pos = pg.Vector2(positions[i, 0], positions[i, 1])
            b.rect.center = b.pos
            b.image = pg.transform.rotate(b.orig_image, -angles[i])
            # b.draw_delta(acceleration[i]*100)


class BoidArray():  # Holds array to store positions and angles

    def __init__(self):
        self.array = torch.zeros((BOIDZ, 3))
        self.forces = torch.zeros((BOIDZ, 2))
        self.boidz = [None] * BOIDZ


def main():
    pg.init()  # prepare window
    pg.display.set_caption("PyNBoids")
    try:
        pg.display.set_icon(pg.image.load("nboids.png"))
    except:
        print("FYI: nboids.png icon not found, skipping..")
    # setup fullscreen or window mode
    if FLLSCRN:
        currentRez = (pg.display.Info().current_w, pg.display.Info().current_h)
        screen = pg.display.set_mode(currentRez, pg.SCALED)
        pg.mouse.set_visible(False)
    else:
        screen = pg.display.set_mode((WIDTH, HEIGHT), pg.RESIZABLE)

    nBoids = pg.sprite.Group()
    dataArray = BoidArray()
    for n in range(BOIDZ):
        nBoids.add(Boid(n, dataArray, screen,
                        FISH))  # spawns desired # of boidz

    clock = pg.time.Clock()
    if SHOWFPS: font = pg.font.Font(None, 30)

    # main loop
    while True:
        for e in pg.event.get():
            if e.type == pg.QUIT or e.type == pg.KEYDOWN and e.key == pg.K_ESCAPE:
                return

        dt = clock.tick(FPS) / 1000
        screen.fill(BGCOLOR)
        nBoids.update(dt, SPEED, WRAP)
        nBoids.draw(screen)

        if SHOWFPS:
            screen.blit(
                font.render(str(int(clock.get_fps())), True, [0, 200, 0]),
                (8, 8))

        with torch.no_grad():
            pg.display.update()


if __name__ == '__main__':
    main()  # by Nik
    pg.quit()
