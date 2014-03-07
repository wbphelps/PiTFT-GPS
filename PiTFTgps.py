#!/usr/bin/python

# PiTFT display engine for GPS
# This must run as root (sudo python lapse.py) due to framebuffer, etc.
#
# http://www.adafruit.com/products/998  (Raspberry Pi Model B)
# http://www.adafruit.com/products/1601 (PiTFT Mini Kit)
#
# Prerequisite tutorials: aside from the basic Raspbian setup and PiTFT setup
# http://learn.adafruit.com/adafruit-pitft-28-inch-resistive-touchscreen-display-raspberry-pi
#
# (c) Copyright 2014 William B. Phelps

import wiringpi2 as wiringpi
import errno
import os, sys, signal
import traceback

import pygame
from pygame.locals import *

from time import sleep
from datetime import datetime, timedelta
import ephem #, ephem.stars
import math
import logging
#import threading

from pyGPS import pyGPS, satInfo

# -------------------------------------------------------------

switch_1 = 1 # GPIO pin 18 - left to right with switches on the top
switch_2 = 2 # GPIO pin 21/27
switch_3 = 3 # GPIO pin 22
switch_4 = 4 # GPIO pin 23

backlightpin = 252

# set up initial observer location
obs = ephem.Observer()
obs.lat = math.radians(37.4388)
obs.lon = math.radians(-122.124)

tNow = datetime.utcnow()
obs.date = tNow

Red = pygame.Color('red')
Orange = pygame.Color('orange')
Green = pygame.Color('green')
Blue = pygame.Color('blue')
Yellow = pygame.Color('yellow')
Cyan = pygame.Color('cyan')
Magenta = pygame.Color('magenta')
White = pygame.Color('white')
Black = (0,0,0)
R90 = math.radians(90) # 90 degrees in radians

# ---------------------------------------------------------------

def StopAll():
    print 'StopAll'
    global gps_on
    if gps_on:
      gps.stop()
    sleep(1)
    pygame.quit()

def Exit():
    print 'Exit'
    StopAll()
    sys.exit(0)

def signal_handler(signal, frame):
    print 'SIGNAL {}'.format(signal)
    Exit()

def backlight(set):
    os.system("echo 252 > /sys/class/gpio/export")
    os.system("echo 'out' > /sys/class/gpio/gpio252/direction")
    if (set):
#        gpio.digitalWrite(backlightpin,gpio.LOW)
        os.system("echo '1' > /sys/class/gpio/gpio252/value")
    else:
#        gpio.digitalWrite(backlightpin,gpio.HIGH)
        os.system("echo '0' > /sys/class/gpio/gpio252/value")

def Shutdown():
    command = "/usr/bin/sudo /sbin/shutdown -f now"
    import subprocess
    process = subprocess.Popen(command.split(), stdout=subprocess.PIPE)
    output = process.communicate()[0]
    print output

# ---------------------------------------------------------------------

def checkButtons():

    sw1 = not wiringpi.digitalRead(switch_1) # Read switch
    if sw1: print 'switch 1'
    sw2 = not wiringpi.digitalRead(switch_2) # Read switch
    if sw2: print 'switch 2'
    sw3 = not wiringpi.digitalRead(switch_3) # Read switch
    if sw3: print 'switch 3'
    sw4 = not wiringpi.digitalRead(switch_4) # Read switch
    if sw4: print 'switch 4'

    return False

# ---------------------------------------------------------------------

# Init framebuffer/touchscreen environment variables
os.putenv('SDL_VIDEODRIVER', 'fbcon')
os.putenv('SDL_FBDEV'      , '/dev/fb1')
os.putenv('SDL_MOUSEDRV'   , 'TSLIB')
os.putenv('SDL_MOUSEDEV'   , '/dev/input/touchscreen')

# Set up GPIO pins
wiringpi.wiringPiSetup() # use wiringpi pin numbers

wiringpi.pinMode(switch_1,0) # input
wiringpi.pullUpDnControl(switch_1, 2)
wiringpi.pinMode(switch_2,0) # input
wiringpi.pullUpDnControl(switch_2, 2)
wiringpi.pinMode(switch_3,0) # input
wiringpi.pullUpDnControl(switch_3, 2)
wiringpi.pinMode(switch_4,0) # input
wiringpi.pullUpDnControl(switch_4, 2)

# Init pygame and screen
pygame.init() 

pygame.mouse.set_visible(False)
size = pygame.display.list_modes(16)[0] # get screen size
#print "size: {}".format(size)

#screen = pygame.display.set_mode(size, FULLSCREEN, 16)
screen = pygame.display.set_mode(size)
(width, height) = size

backlight(True)

# start the GPS thread running
gps = pyGPS()
gps.start()
gps_on = True

#bg = pygame.image.load("ISSTracker7.png")
bg = pygame.Surface((320,240))
bg.fill((0,0,0))
bgRect = bg.get_rect()
txtColor = Yellow
txtFont = pygame.font.SysFont("Arial", 30, bold=True)
txt = txtFont.render('PiTFT GPS' , 1, txtColor)
bg.blit(txt, (15, 28))
txt = txtFont.render('by' , 1, txtColor)
bg.blit(txt, (15, 64))
txt = txtFont.render('William Phelps' , 1, txtColor)
bg.blit(txt, (15, 100))
screen.blit(bg, bgRect)
pygame.display.update()
sleep(3)

#  ----------------------------------------------------------------

logging.basicConfig(filename='/home/pi/isstracker/isstracker.log',filemode='w',level=logging.DEBUG)
logging.info("ISS-Tracker System Startup")

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGHUP, signal_handler)
signal.signal(signal.SIGQUIT, signal_handler)
#print "sigterm handler set"


while(True):

  try:
    from showGPS import showGPS

    utcNow = datetime.utcnow()
    obs.date = utcNow
    sun = ephem.Sun(obs)

    sGPS = showGPS(screen, gps, obs, sun) # set up the GPS display screen

    # show the sky with GPS positions & signal
    while True:

      obs.date = utcNow # update observer time
      sun = ephem.Sun(obs) # recompute sun
      sGPS.plot(gps, obs, sun)
      sec = utcNow.second
      while sec == utcNow.second: # wait for clock to tic
        if checkButtons(): break
        sleep(0.1)
        utcNow = datetime.utcnow()

      if gps.quality > 0:
        obs.lat = gps.avg_latitude
        obs.lon = gps.avg_longitude
      elif gps.status == 'A':
        obs.lat = gps.latitude
        obs.lon = gps.longitude

  except SystemExit:
    print 'SystemExit'
    sys.exit(0)
  except:
    print '"Except:', sys.exc_info()[0]
    page = None
#    print traceback.format_exc()
    StopAll()
    raise
