#!/usr/bin/python3 -u
# mihome_energy_monitor.py  28/05/2016  D.J.Whale
# Extended with MQTT publishing by Andrew Gillard, 2020-12
#
# Listens for data (e.g. energy usage) from Energenie Mi|Home devices,
#  publishing via MQTT all data received from devices in the local "registry".
# Devices can be added to the registry (and renamed, etc.) using the
#  "2. mihome discovery mode" menu item of the `setup_tool.py` script in this
#  repository: run `python setup_tool.py` to access it.
# TODO Optionally publish ALL received data, regardless of existence in
#      registry (if possible).

import energenie
import Logger
from energenie import OpenThings
import time
#import os, time
from datetime import datetime, timezone
from dateutil import tz
#import sys
#import os
#import socket
import json
#import paho.mqtt.client as mqtt

APP_DELAY    = 2
timezoneUtc = timezone.utc
timezoneLocal = tz.gettz('Europe/London')

def getDataFromMessage(msg):
    # Get UTC time with timezone info so we can publish to MQTT with a
    #  full ISO8601 format, including timezone offset.
    now = datetime.now(timezoneUtc)
    timestamp = time.time()
    isodate   = now.isoformat()

    header    = msg['header']
    mfrid     = header['mfrid']
    productid = header['productid']
    sensorid  = header['sensorid']

    # set defaults for any data that doesn't appear in this message
    # but build flags so we know which ones this contains
    # `flags` indicates which fields were present in the decoded message.
    flags = [0 for i in range(8)]
    switch = None
    voltage = None
    freq = None
    reactive = None
    real = None
    apparent = None
    current = None
    temperature = None

    # Extract the data fields
    for rec in msg['recs']:
        paramid = rec['paramid']
        try:
            value = rec['value']
        except:
            value = None

        if   paramid == OpenThings.PARAM_SWITCH_STATE:
            switch = value
            flags[0] = 1
        elif paramid == OpenThings.PARAM_DOOR_SENSOR:
            switch = value
            flags[0] = 1
        elif paramid == OpenThings.PARAM_VOLTAGE:
            flags[1] = 1
            voltage = value
        elif paramid == OpenThings.PARAM_FREQUENCY:
            flags[2] = 1
            freq = value
        elif paramid == OpenThings.PARAM_REACTIVE_POWER:
            flags[3] = 1
            reactive = value
        elif paramid == OpenThings.PARAM_REAL_POWER:
            flags[4] = 1
            real = value
        elif paramid == OpenThings.PARAM_APPARENT_POWER:
            flags[5] = 1
            apparent = value
        elif paramid == OpenThings.PARAM_CURRENT:
            flags[6] = 1
            current = value
        elif paramid == OpenThings.PARAM_TEMPERATURE:
            # e.g. Thermostatic radiator valves (eTRV)
            flags[7] = 1
            temperature = value

    # `flagsStr` will be a binary-esque string indicating which data were
    #  present in the decoded message; left to right:
    # 0=switch/door-sensor, 1=voltage, 2=frequency, 3=reactive-power,
    # 4=real-power, 5=apparent-power, 6=current, 7=temperature
    flagsStr = "".join([str(a) for a in flags])

    #csv = "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s" % (timestamp, mfrid, productid, sensorid, flags, switch, voltage, freq, reactive, real, apparent, current, temperature)
    # Example from CSV:
    #timestamp,mfrid,prodid,sensorid,flags,switch,voltage,freq,reactive,real,apparent,current,temperature
    #1609377853.89,4,1,7933,01111000,None,241,49.8515625,-91,148,None,None,None
    #1609377856.35,4,1,7850,01111000,None,243,50.05078125,0,5,None,None,None
    #1609377859.39,4,2,16777114,11111000,1,244,49.80078125,4,4,None,None,None
    #1609377859.93,4,1,1103,01111000,None,243,49.80078125,-134,83,None,None,None
    #1609377865.63,4,2,9623,11111000,0,242,49.94921875,0,0,None,None,None
    #return (timestamp, mfrid, productid, sensorid, flagsStr, switch, voltage, freq, reactive, real, apparent, current, temperature)
    #return (timestamp, mfrid, productid, sensorid, flags, switch, voltage, freq, reactive, real, apparent, current, temperature)
    # TODO Make this return an object for easier use.
    return {
            'timestamp': timestamp,
            'datetime': isodate,
            'manufId': mfrid,
            'prodId': productid,
            'sensorId': sensorid,
            'flagsStr': flagsStr,
            'flags': {
                'switch': flags[0],
                'voltage': flags[1],
                'frequency': flags[2],
                'powerReactive': flags[3],
                'powerReal': flags[4],
                'powerApparent': flags[5],
                'current': flags[6],
                'temperature': flags[7],
            },
            'switch': switch,
            'voltage': voltage,
            'frequency': freq,
            'powerReal': real,
            'powerApparent': apparent,
            'powerReactive': reactive,
            'current': current,
            'temperature': temperature,
    }

def energy_monitor_loop():
    # Process any received messages from the real radio
    # TODO Is this where "new device found; add to registry?" messages are generated?
    # TODO "New device found" prompts need to be handled automatically for this script to run as a daemon!
    energenie.loop()

    # For all devices in the registry, if they have a get_power(), call it
    #print("Checking device status")
    #for d in energenie.registry.devices():
        #print(">> {0}".format(d))
    #    try:
            # TODO Does this ever do anything? I don't think I've seen one of these messages...
            # TODO Maybe all the data is handled by the `energenie.loop()` line, above?
            # TODO (Unless we have to call this to prompt devices to report data? Seems unlikely when the regular Energenie hub will be collecting data all the time anyway...)
    #        p = d.get_power()
    #        print("Power: %f" % p)
    #    except:
    #        pass # Ignore it if can't provide a power

    time.sleep(APP_DELAY)


if __name__ == "__main__":
    #print("Starting energy monitor example")
    energenie.init()

    # Default incoming message handler, for MQTT-publishing every message.
    # TODO Publish this data to MQTT
    def incoming(address, message):
        # `address` is a tuple of (manufId, prodId, sensorId), which are
        #  all in the `data` object returned from `getDataFromMessage()`.
        # So `address` doesn't have to be returned separately.
        # Example:
        #  manufId:4, sensorId:2047, prodId:1
        #  address:(4, 1, 2047)

        #print("\nIncoming from {0} :: {1}".format(str(address), message))
        data = getDataFromMessage(message)
        print("Data [{0}]: {1}".format(address, data))

    energenie.fsk_router.when_incoming(incoming)

    try:
        while True:
            energenie.loop()
            time.sleep(APP_DELAY)

            #energy_monitor_loop()
    except KeyboardInterrupt:
        print("Interrupted. Exiting.")
        exit(0)
    except Exception as e:
        # `Exception` is the base class of all exceptions that we're "supposed"
        # to catch in most situations. It excludes KeyboardInterrupt, SystemExit,
        # GeneratorExit (which use BaseException instead).
        exit("Unexpected '{0}' error: {1}".format(type(e), e))
    finally:
        energenie.finished()

