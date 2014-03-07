# a class to support serial GPS devices
# parses 3 NMEA sentences: RMC, GGA, GSV
# runs as a thread
# computes running average of the last 10 position values
#
# Copyright (c) 2014 William B Phelps
#

import time, serial, sys
from datetime import datetime, timedelta
import threading
import math

''' NMEA Message formats

  $GPRMC,225446.000,A,4916.45,N,12311.12,W,000.5,054.7,191194,020.3,E*68\r\n
  225446       Time of fix 22:54:46 UTC
  A            Navigation receiver warning A = OK, V = warning
  4916.45,N    Latitude 49 deg. 16.45 min North
  12311.12,W   Longitude 123 deg. 11.12 min West
  000.5        Speed over ground, Knots
  054.7        Course Made Good, True
  191194       Date of fix 19 November 1994
  020.3,E      Magnetic variation 20.3 deg East
  *68          mandatory checksum

  $GPGGA,hhmmss.ss,llll.ll,a,yyyyy.yy,a,x,xx,x.x,x.x,M,x.x,M,x.x,xxxx*hh
  1    = UTC of Position
  2    = Latitude
  3    = N or S
  4    = Longitude
  5    = E or W
  6    = GPS quality indicator (0=invalid; 1=GPS fix; 2=Diff. GPS fix)
  7    = Number of satellites in use [not those in view]
  8    = Horizontal dilution of position
  9    = Antenna altitude above/below mean sea level (geoid)
  10   = Meters  (Antenna height unit)
  11   = Geoidal separation (Diff. between WGS-84 earth ellipsoid and
         mean sea level.  -=geoid is below WGS-84 ellipsoid)
  12   = Meters  (Units of geoidal separation)
  13   = Age in seconds since last update from diff. reference station
  14   = Diff. reference station ID#
  15   = Checksum

  $GPGSV,3,1,11,03,03,111,00,04,15,270,00,06,01,010,00,13,06,292,00*74
  $GPGSV,3,2,11,14,25,170,00,16,57,208,39,18,67,296,40,19,40,246,00*74
  $GPGSV,3,3,11,22,42,067,42,24,14,311,43,27,05,244,00,,,,*4D

  1    = Total number of messages of this type in this cycle
  2    = Message number
  3    = Total number of SVs in view
  4    = SV PRN number
  5    = Elevation in degrees, 90 maximum
  6    = Azimuth, degrees from true north, 000 to 359
  7    = SNR, 00-99 dB (null when not tracking)
  8-11 = Information about second SV, same as field 4-7
  12-15= Information about third SV, same as field 4-7
  16-19= Information about fourth SV, same as field 4-7

'''

def tz_offset():
  #Return offset of local zone from GMT
  t = time.time()
  if time.localtime(t).tm_isdst and time.daylight:
    return -time.altzone
  else:
    return -time.timezone

def c2Float(str):
  try:
     f = float(str)
  except:
     print 'c2float error {}'.format(str)
     f = 0
  return f

def c2Int(str):
  try:
     i = int(str)
  except:
     print 'c2int error {}'.format(str)
     i = 0
  return i

# check serial port???
#port = serial.Serial("/dev/ttyAMA0", baudrate=9600, timeout=3.0)
#port = serial.Serial("/dev/ttyUSB0", baudrate=4800, timeout=3.0)

class satInfo():
  def __init__(self,svn,alt,azi,snr):
    self.svn = svn # SV PRN
    self.alt = alt # altitude
    self.azi = azi # azimuth
    self.snr = snr # S/N ratio

class pyGPS():

  def __init__(self,device='/dev/ttyAMA0',baudrate=9600,timeout=3.0):
    self.device = device
    self.baudrate = baudrate
    self.timeout = timeout
    self.running = False
    self._run = False
    self.statusOK = False
    self.status = 'x' # 'A' or 'V'
    self.satellites = []
    self.lock = threading.Lock()
    self.latitude = 0
    self.longitude = 0
    self.datetime = None
    self.port = serial.Serial(self.device,baudrate=self.baudrate, timeout=self.timeout)
    self.rcv = '' # buffer
    self.i = 0 # buffer index
    self.error = ''
    self.quality = 0
    self.altitude = 0
    self.hDilution = 0
    self.geodiff = 0
    self.l10_lat = [0,0,0,0,0,0,0,0,0,0] # last 10 latitude values
    self.l10_lon = [0,0,0,0,0,0,0,0,0,0]
    self.avg_latitude = 0 # position averaging (simple)
    self.avg_longitude = 0 # position averaging (simple)

  def __exit__(self, type, value, traceback):
    self.port.close() # close serial port
    print 'GPS exit'

  def check(self,rcv):
    # calculate checksum
    chk1 = 0
    i = 0
    for ch in rcv:
      if (ch == '*'):
        break
      chk1 = chk1 ^ ord(ch)
      i += 1
    chk2 = int(rcv[i+1:i+3],16)
#    print("chk1:" + hex(chk1) + " chk2:" + hex(chk2))
    if (chk1 != chk2):
      print "Checksum error"
      return False
    else:
      return True

  def ntok(self):
    i2 = self.rcv.find(',', self.i) # find next comma
    if (i2 < 0): return ''
    tk = self.rcv[self.i:i2]
    self.i = i2 + 1
    return tk

  def getGPS(self):
    print 'GPS start'
    with self.lock:
      if self.running:
        print "GPS: error already running"
        return
      self.running = True
    sats = []
    while self._run:
      self.rcv = self.port.readline()
      try:

#  $GPGGA,hhmmss.ss,llll.ll,a,yyyyy.yy,a,q,ns,h.d,a.a,M,x.x,M,x.x,xxxx*hh
        if (self.rcv[:7] == '$GPGGA,'):
          self.rcv = self.rcv[1:] # remove $
#          print("rcv:" + repr(self.rcv))
          if self.check(self.rcv): # check checksum
            self.i = 6 # start at 1st token
            gtime = self.ntok()[:6]
            lat = c2Float(self.ntok())
            lat = lat//100 + (lat%100)/60.0
            latD = self.ntok()
            if latD == 'S': lat = -lat
            lon = c2Float(self.ntok())
            lon = lon//100 + (lon%100)/60.0
            lonD = self.ntok()
            if lonD == 'W': lon = -lon
            quality = c2Int(self.ntok())
            nsats = c2Int(self.ntok())
            hDilution = c2Float(self.ntok())
            altitude = c2Float(self.ntok())
            altu = self.ntok()
            geodiff = c2Float(self.ntok())
            gdiffu = self.ntok()
#            print 't: {}, q: {}, alt: {}'.format(gtime,quality, alt)
            if quality>0:
#              print 'alt:{}'.format(alt)
              with self.lock:
                self.quality = quality
                self.altitude = altitude
                self.geodiff = geodiff
                self.hDilution = hDilution
                self.l10_lat.append(lat)
                self.l10_lat = self.l10_lat[1:]
                self.l10_lon.append(lon)
                self.l10_lon = self.l10_lon[1:]
                self.avg_latitude = math.radians(sum(self.l10_lat)/10.0)
                self.avg_longitude = math.radians(sum(self.l10_lon)/10.0)
#              if gtime == '':
#                print("quality: {}, lat: {}{}, lon: {}{}, time: {}".format(quality,  latD, lat, lonD, lon, 0))
#              else:
#                print 'gtime: "{}"'.format(gtime)
#                t = datetime.strptime(gtime, "%H%M%S")
#                print("quality: {}, lat: {}{}, lon: {}{}, alt {}{}, gdiff {}{}, time: {}".format(quality,  latD, lat,
#                  lonD, lon, alt, altu, gdiff, gdiffu, t))

        if (self.rcv[:7] == '$GPGSV,'): # satellite info
          self.rcv = self.rcv[1:] # remove $
#          print("rcv:" + repr(self.rcv))
          if self.check(self.rcv):
            self.i = 6 # start at 1st token
            nmsgs = self.ntok()
            msgn = self.ntok()
            nsats = self.ntok()
            if (msgn == "1"):
              sats = []
            while True:
              svn = self.ntok()
              if (not svn.isdigit()):
                break;
#              print 'i: {}, svn: {}'.format(self.i,svn)
              alt, azi, snr = 0,0,0
              talt = self.ntok()
              if talt.isdigit(): alt = int(talt)
              tazi = self.ntok()
              if tazi.isdigit(): azi = int(tazi)
              tsnr = self.ntok()
              if tsnr.isdigit(): snr = int(tsnr)
              sats.append(satInfo(svn,math.radians(alt),math.radians(azi),snr))
            if (msgn == nmsgs): # last gpgsv message?
              with self.lock:
                self.satellites = sats
#              s1 = ""
#              ns = 0
#              for sat in sats:
#                if (sat.snr>0):
#                  ns += 1
#                  s1 = s1 + "{}:{},{},{}, ".format(sat.svn,math.degrees(sat.alt),math.degrees(sat.azi),sat.snr)
#              print('{:0>2}/{:2} sats {!s}'.format(ns, nsats, s1))

        if (self.rcv[:7] == '$GPRMC,'): # required miminum 
          self.rcv = self.rcv[1:] # remove $
#          print("rcv:" + repr(self.rcv))
          if self.check(self.rcv): # check checksum
            self.i = 6 # start at 1st token
            gtime = self.ntok()[:6]
            self.status = self.ntok()
#            print ("status: " + self.status)
            lat = c2Float(self.ntok())
            lat = lat//100 + (lat%100)/60.0
            latD = self.ntok()
            if latD == 'S': lat = -lat
            lon = c2Float(self.ntok())
            lon = lon//100 + (lon%100)/60.0
            lonD = self.ntok()
            if lonD == 'W': lon = -lon
            spd = self.ntok()
            crs = self.ntok()
            gdate = self.ntok()
            mag = self.ntok()
            dt = datetime.strptime(gdate+gtime, "%d%m%y%H%M%S") + timedelta(seconds=tz_offset())
#            print("status: {}, lat: {}, lon: {}, time: {}".format(self.status, lat, lon, dt))
            with self.lock:
              self.statusOK = False
              self.latitude = math.radians(lat)
              self.longitude = math.radians(lon)
              self.datetime = dt
              if self.status == 'A':
                self.statusOK = True
      except:
        print self.rcv
        print ("Error: "),sys.exc_info()[0]
        self.error = format(sys.exc_info()[0])
        raise
    print 'GPS stop'  

  def start(self):
    with self.lock:
      if self.running == False:
#        print "bl: start thread"
        self._run = True
        self.thread = threading.Thread(target = self.getGPS)
        self.thread.start()

  def stop(self):
    with self.lock:
      self._run = False # stop loop


