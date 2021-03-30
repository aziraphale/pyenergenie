#!/usr/bin/python3 -u
# vim: set fileencoding=utf-8 :

# mihome_energy_monitor.py  28/05/2016  D.J.Whale
# Extended with MQTT publishing by Andrew Gillard, 2020-12
#
# Listens for data (e.g. energy usage) from Energenie Mi|Home devices,
#  publishing via MQTT all data received from devices in the local "registry".
# Devices can be added to the registry (and renamed, etc.) using the
#  "2. mihome discovery mode" menu item of the `setup_tool.py` script in this
#  repository: run `python setup_tool.py` to access it.
#
# MQTT topic has this format:
#  <$MQTT_TOPIC>/<manuf ID>/<manuf name>/<prod ID>/<prod code>/<prod name>/<device ID>
# e.g.:
#  energenie/4/Energenie/5/MIHO006/HomeMonitor/12345
#  energenie/4/Energenie/1/MIHO004/Monitor/1337
#  energenie/4/Energenie/2/MIHO005/AdaptorPlus/16777210
# Where:
# - `$MQTT_TOPIC` is the topic prefix set by the MQTT_TOPIC environment
#    variable; e.g. "energenie".
# - `manuf ID` is the numeric manufacturer ID received; e.g. `4`=Energenie.
#     - This will probably always be 4 for Energenie. I'm not aware of other
#       manufacturers using this system.
#     - See below list of known manufacturers.
# - `manuf name` is the manufacturer's name, if the manufacturer ID is
#    recognised; e.g. "Energenie".
#     - Again, this will likely always be "Energenie".
#     - See below list of known manufacturers.
# - `prod ID` is the numeric product ID received; e.g. `1`="pink" monitor-only
#    sockets, `5`=whole-house monitor.
#     - See below list of known products.
# - `prod code` is the "MIHOxxx" product "code", if the product ID is
#    recognised; e.g. "MIHO004"=monitor-only socket.
#     - (NOTE: Energenie product codes consist of "MIHO" as letters, followed
#       by 3 digits, e.g. "004". Do not confuse "MIHO"'s capital "o" with the
#       zeroes in the digits!)
#     - See below list of known products.
# - `prod name` is the product "name".
#     - I'm not sure if this is "official" in any way, or just the name used
#       by the `pyenergenie` library on which this service is based, but it's
#       a more easily-recognisable way of identifying products than their IDs
#       or codes, at least.
#     - See below list of known products.
# - `device ID` is the numeric unique ID assigned to each individual device;
#    e.g. `12345`.
#     - This is probably set when each device is manufactured, as opposed to
#       being a number assigned by the Mi|Home service when they're paired.
#     - Firstly, many Energenie devices are unable to receive RF signals at all
#       (e.g. monitor-only sockets, whole-house monitor), so it wouldn't be
#       possible to tell the device its new ID when it was paired (and this is
#       a number that's transmitted BY each device, so it has to know what its
#       ID is).
#     - Secondly, my older devices have IDs with lower numbers than my newer
#       devices, even older devices that sat unused for a couple of years
#       without being paired!
#
# Known Manufacturers:
#  ID       NAME
#  4        Energenie
#
# Known Products:
#  ID       CODE        NAME            DESCRIPTION
#  1        MIHO004     Monitor         Socket, monitor-only, pink text.
#  2        MIHO005     AdaptorPlus     Socket, monitor+switch, purple text.
#  3        MIHO013     eTRV            Thermostatic radiator valve.
#  5        MIHO006     HomeMonitor     Whole-house electricity meter clamp.
#  12       MIHO032     MotionSensor    Motion sensor (PIR).
#  13       MIHO033     OpenSensor      Door/window open sensor (reed switch).
# (These are the only products defined in `./energenie/Devices.py`)

# NOTE Only MQTT QoS>0 (1 or 2) msgs will be queued/retried by paho-mqtt!

# TODO Optionally publish ALL received data, regardless of existence in
#       registry (if possible).

# Dependencies:
# - Python 3
#   - This was written for, and tested with, Python 3.4, on
#      Raspbian/Raspberry Pi OS "jessie", on a Raspberry Pi Zero V1.3
#      (yes, in 2021! This RPi needs updating!).
#   - Newer versions of Python 3 should work, as should newer versions of
#      Raspbian/Raspberry Pi OS, and other Raspberry Pi boards. Let me know
#      if that's not the case!
#   - Python 2 is explicitly UNTESTED: it's end-of-life and not supported.
#      You need to start using Python 3!
# - dateutil
#   - pip install python-dateutil
#   - https://pypi.org/project/python-dateutil/
#   - https://dateutil.readthedocs.io/
# - paho-mqtt
#   - pip install paho-mqtt
#   - https://pypi.org/project/paho-mqtt/
# - pyenergenie
#   - https://github.com/whaleygeek/pyenergenie
#   - https://github.com/Energenie/pyenergenie

import energenie
import Logger
from energenie import OpenThings
from energenie import Devices
import time
#import os, time
from datetime import datetime, timezone
from dateutil import tz
import sys
import os
import socket
import json
import paho.mqtt.client as mqtt

APP_DELAY    = 2

mqttHost = "localhost"
mqttPort = 1883 # MQTT=1883, MQTT+TLS=8883
mqttUser = ""
mqttPass = ""
mqttClientId = "energenie_{0}_{1}".format(socket.gethostname(), os.getpid())
mqttCleanSession = True
mqttBindAddress = None
mqttKeepalive = 60
mqttProtocolVersion = mqtt.MQTTv311 # MQTTv31 or MQTTv311
mqttReconnectDelayMin = 1 # min secs to wait between reconnection attempts
mqttReconnectDelayMax = 120 # max secs to wait between reconnection attempts
mqttTopic = "energenie"
mqttWillPayload = "Offline"
mqttQoS = 1
mqttRetain = True
mihomeListenerName = socket.gethostname()
timezoneUtc = timezone.utc
timezoneLocal = tz.gettz('Europe/London')

if os.getenv('MQTT_HOST') is not None:
    mqttHost = os.getenv('MQTT_HOST')

if os.getenv('MQTT_PORT') is not None:
    mqttPort = int(os.getenv('MQTT_PORT'))

if os.getenv('MQTT_USER') is not None:
    mqttUser = os.getenv('MQTT_USER')

if os.getenv('MQTT_PASS') is not None:
    mqttPass = os.getenv('MQTT_PASS')

if os.getenv('MQTT_CLIENT_ID') is not None:
    mqttClientId = os.getenv('MQTT_CLIENT_ID')

if os.getenv('MQTT_CLEAN_SESSION') is not None:
    mqttCleanSession = os.getenv('MQTT_CLEAN_SESSION').lower() in ['1', 'true']

if os.getenv('MQTT_BIND_ADDRESS') is not None:
    mqttBindAddress = os.getenv('MQTT_BIND_ADDRESS')

if os.getenv('MQTT_KEEPALIVE') is not None:
    mqttKeepalive = int(os.getenv('MQTT_KEEPALIVE'))

if os.getenv('MQTT_PROTO_VERSION') is not None:
    # TODO It'd be nice to support future protocol versions without having to update this list.
    #      Can that be done while still performing some validation here?
    envProtoVersion = os.getenv('MQTT_PROTO_VERSION')
    if envProtoVersion.lower() == 'mqttv31':
        mqttProtocolVersion = mqtt.MQTTv31
    elif envProtoVersion.lower() == 'mqttv311':
        mqttProtocolVersion = mqtt.MQTTv311
    else:
        # TODO Maybe raise exception here instead?
        # exit("...") writes to stderr and exits with status=1
        exit("MQTT_PROTO_VERSION env var must be 'MQTTv31' or 'MQTTv311', not '{0}'!".format(envProtoVersion))

if os.getenv('MQTT_RECONNECT_MIN_DELAY_SECS') is not None:
    mqttReconnectDelayMin = int(os.getenv('MQTT_RECONNECT_MIN_DELAY_SECS')) # TODO Validation + sanity check

if os.getenv('MQTT_RECONNECT_MAX_DELAY_SECS') is not None:
    mqttReconnectDelayMax = int(os.getenv('MQTT_RECONNECT_MAX_DELAY_SECS')) # TODO Validation + sanity check

if os.getenv('MQTT_TOPIC') is not None:
    mqttTopic = os.getenv('MQTT_TOPIC') # TODO Add some validation

if os.getenv('MQTT_WILL_PAYLOAD') is not None:
    mqttWillPayload = os.getenv('MQTT_WILL_PAYLOAD')

if os.getenv('MQTT_QOS') is not None:
    mqttQoS = int(os.getenv('MQTT_QOS')) # TODO Validate

if os.getenv('MQTT_RETAIN') is not None:
    mqttRetain = os.getenv('MQTT_RETAIN').lower() in ['1', 'true']

if os.getenv('MIHOME_LISTENER_NAME') is not None:
    mihomeListenerName = os.getenv('MIHOME_LISTENER_NAME')

def mqttOnConnect(client, userdata, flags, rc):
    if rc == 0: # aka MQTT_ERR_SUCCESS
        print("MQTT connected!", file=sys.stderr)
    else:
        permafail = False
        if rc == 1:
            print("MQTT connection failed; code {0}: refused - incorrect protocol version".format(rc), file=sys.stderr)
            permafail = True
        elif rc == 2:
            print("MQTT connection failed; code {0}: refused - invalid client identifier".format(rc), file=sys.stderr)
            permafail = True
        elif rc == 3:
            print("MQTT connection failed; code {0}: refused - server unavailable".format(rc), file=sys.stderr)
        elif rc == 4:
            print("MQTT connection failed; code {0}: refused - bad username or password".format(rc), file=sys.stderr)
            permafail = True
        elif rc == 5:
            print("MQTT connection failed; code {0}: refused - not authorised".format(rc), file=sys.stderr)
            permafail = True
        else:
            print("MQTT connection failed with unrecognised error code '{0}'!".format(rc), file=sys.stderr)

        if permafail:
            # exit("...") writes to stderr and exits with status=1
            exit("Permanent connection failure reason. Exiting.")

def mqttOnDisconnect(client, userdata, rc):
    if rc == 0: # aka MQTT_ERR_SUCCESS
        print("MQTT disconnected in response to a call to `disconnect()` [on_disconnect reason code = 0]", file=sys.stderr)
    else:
        print("MQTT disconnected unexpectedly! [on_disconnect reason code = {0}]".format(str(rc)), file=sys.stderr)

def getDataFromMessage(msg):
    # Get UTC time with timezone info so we can publish to MQTT with a
    #  full ISO8601 format, including timezone offset.
    now = datetime.now(timezoneUtc)
    timestamp = time.time()
    isodate   = now.isoformat()

    header    = msg['header']
    manufId   = header['mfrid']
    prodId    = header['productid']
    sensorId  = header['sensorid']

    # set defaults for any data that doesn't appear in this message
    # but build flags so we know which ones this contains
    # `flags` indicates which fields were present in the decoded message.
    flags       = [False for i in range(8)]
    switch      = None
    voltage     = None
    freq        = None
    reactive    = None
    real        = None
    apparent    = None
    current     = None
    temperature = None

    # Extract the data fields
    for rec in msg['recs']:
        paramId = rec['paramid']
        try:
            value = rec['value']
        except:
            value = None

        if   paramId == OpenThings.PARAM_SWITCH_STATE:
            flags[0] = True
            switch = value
        elif paramId == OpenThings.PARAM_DOOR_SENSOR:
            flags[0] = True
            switch = value
        elif paramId == OpenThings.PARAM_VOLTAGE:
            flags[1] = True
            voltage = value
        elif paramId == OpenThings.PARAM_FREQUENCY:
            flags[2] = True
            freq = value
        elif paramId == OpenThings.PARAM_REACTIVE_POWER:
            flags[3] = True
            reactive = value
        elif paramId == OpenThings.PARAM_REAL_POWER:
            flags[4] = True
            real = value
        elif paramId == OpenThings.PARAM_APPARENT_POWER:
            flags[5] = True
            apparent = value
        elif paramId == OpenThings.PARAM_CURRENT:
            flags[6] = True
            current = value
        elif paramId == OpenThings.PARAM_TEMPERATURE:
            # e.g. Thermostatic radiator valves (eTRV)
            flags[7] = True
            temperature = value

    # `flagsStr` will be a binary-esque string indicating which data were
    #  present in the decoded message; left to right:
    # 0=switch/door-sensor, 1=voltage, 2=frequency, 3=reactive-power,
    # 4=real-power, 5=apparent-power, 6=current, 7=temperature
    #flagsStr = "".join([str(int(a)) for a in flags])

    #csv = "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s" % (timestamp, mfrid, productid, sensorid, flags, switch, voltage, freq, reactive, real, apparent, current, temperature)
    # Example from CSV:
    #timestamp,mfrid,prodid,sensorid,flags,switch,voltage,freq,reactive,real,apparent,current,temperature
    #1609377853.89,4,1,7933,01111000,None,241,49.8515625,-91,148,None,None,None
    #1609377856.35,4,1,7850,01111000,None,243,50.05078125,0,5,None,None,None
    #1609377859.39,4,2,16777114,11111000,1,244,49.80078125,4,4,None,None,None
    #1609377859.93,4,1,1103,01111000,None,243,49.80078125,-134,83,None,None,None
    #1609377865.63,4,2,9623,11111000,0,242,49.94921875,0,0,None,None,None
    #return (timestamp, mfrid, productid, sensorid, flagsStr, switch, voltage, freq, reactive, real, apparent, current, temperature)

    manufName = manufIdToName(manufId)
    prodCode = prodIdToCode(prodId)
    prodName = prodIdToName(prodId)

    return {
            'Timestamp':        timestamp,
            'DateTime':         isodate,
            'Source':           mihomeListenerName,
            'ManufacturerID':   manufId,
            'ManufacturerName': manufName,
            'ProductID':        prodId,
            'ProductCode':      prodCode,
            'ProductName':      prodName,
            'SensorID':         sensorId,

            'HasSwitch':        flags[0],
            'HasVoltage':       flags[1],
            'HasFrequency':     flags[2],
            'HasReactivePower': flags[3],
            'HasRealPower':     flags[4],
            'HasApparentPower': flags[5],
            'HasCurrent':       flags[6],
            'HasTemperature':   flags[7],

            'SwitchState':      switch,
            'Voltage':          voltage,
            'Frequency':        freq,
            'RealPower':        real,
            'ApparentPower':    apparent,
            'ReactivePower':    reactive,
            'Current':          current,
            'Temperature':      temperature,
    }

# I would have thought that functions like this would exist somewhere in the
#  Energenie library being used here, but I can't immediately find any - just
#  the DeviceFactory for creating objects, which is overkill when we just
#  want the name/code...
def manufIdToName(manufId):
    manufName = None
    if manufId == Devices.MFRID_ENERGENIE:
        manufName = "Energenie"
    return manufName

def prodIdToCode(prodId):
    prodCode = None
    if   prodId == Devices.PRODUCTID_MIHO004:
        prodCode = "MIHO004"
    elif prodId == Devices.PRODUCTID_MIHO005:
        prodCode = "MIHO005"
    elif prodId == Devices.PRODUCTID_MIHO006:
        prodCode = "MIHO006"
    elif prodId == Devices.PRODUCTID_MIHO013:
        prodCode = "MIHO013"
    elif prodId == Devices.PRODUCTID_MIHO032:
        prodCode = "MIHO032"
    elif prodId == Devices.PRODUCTID_MIHO033:
        prodCode = "MIHO033"
    return prodCode

def prodIdToName(prodId):
    prodName = None
    if   prodId == Devices.PRODUCTID_MIHO004:
        prodName = "Monitor"
    elif prodId == Devices.PRODUCTID_MIHO005:
        prodName = "AdaptorPlus"
    elif prodId == Devices.PRODUCTID_MIHO006:
        prodName = "HomeMonitor"
    elif prodId == Devices.PRODUCTID_MIHO013:
        prodName = "eTRV"
    elif prodId == Devices.PRODUCTID_MIHO032:
        prodName = "MotionSensor"
    elif prodId == Devices.PRODUCTID_MIHO033:
        prodName = "OpenSensor"
    return prodName

# Incoming Energenie message handler, to MQTT-publish every message.
def energenie_incoming(address, message):
    # `address` is a tuple of (manufId, prodId, sensorId), which are
    #  all in the `data` object returned from `getDataFromMessage()`.
    # So `address` doesn't have to be returned separately.
    # Example:
    #  manufId:4, sensorId:2047, prodId:1
    #  address:(4, 1, 2047)

    #print("\nIncoming from {0} :: {1}".format(str(address), message))
    data = getDataFromMessage(message)
    #print(data)
    #print("Data [{0}]: {1}".format(address, data))

    topicManufName = data['ManufacturerName']
    topicProdCode = data['ProductCode']
    topicProdName = data['ProductName']
    if topicManufName == None:
        topicManufName = "UNKNOWN"
    if topicProdCode == None:
        topicProdCode = "UNKNOWN"
    if topicProdName == None:
        topicProdName = "UNKNOWN"

    mqttClient.publish(
            # Topic example: energenie/4/1/2047
            mqttTopic + "/{0}/{1}/{2}/{3}/{4}/{5}".format(data['ManufacturerID'], topicManufName, data['ProductID'], topicProdCode, topicProdName, data['SensorID']),
            json.dumps(data),
            qos=mqttQoS,
            retain=mqttRetain
        )


if __name__ == "__main__":
    try:
        # Connect to MQTT...
        mqttClient = mqtt.Client(client_id=mqttClientId,
                clean_session=mqttCleanSession, protocol=mqttProtocolVersion)
        #mqttClient.enable_logger()
        mqttClient.on_connect = mqttOnConnect
        mqttClient.on_disconnect = mqttOnDisconnect

        mqttClient.username_pw_set(username=mqttUser, password=mqttPass)

        # Max num of QoS>0 messages in the process of being sent/acknowledged (default=20)
        # This system seems to receive data in bursts, so it's plausible we might have quite a lot in progress at once.
        # TODO Make this configurable with an env var?
        mqttClient.max_inflight_messages_set(50)
        # Max num of pending QoS>0 messages in the outgoing queue (default=0, aka unlimited)
        #mqttClient.max_queued_messages_set(0)

        # Will - set what the broker will send if we disconnect unexpectedly
        mqttClient.will_set(mqttTopic+'/lwt', mqttWillPayload, qos=mqttQoS, retain=mqttRetain)

        # Min and max delay before reconnecting
        mqttClient.reconnect_delay_set(min_delay=mqttReconnectDelayMin,
                max_delay=mqttReconnectDelayMax)

        bindAddr = ""
        if mqttBindAddress is not None:
            bindAddr = mqttBindAddress

        # Connect in the background thread.
        # This won't connect until loop_start() is called (which *can* be called
        #  *before* this connect_async() function!)
        print("Connecting to MQTT...", file=sys.stderr)
        mqttClient.connect_async(mqttHost, port=mqttPort,
                keepalive=mqttKeepalive, bind_address=bindAddr)

        # Start a new thread to handle network traffic, automatic reconnections, etc.
        mqttClient.loop_start()
    except Exception as e:
        # exit("...") writes to stderr and exits with status=1
        exit("MQTT initialisation failed with '{0}' error: {1}".format(type(e), e))

    print("Initialising Energenie...", file=sys.stderr)
    energenie.init()

    energenie.fsk_router.when_incoming(energenie_incoming)

    # Specify discovery behaviour from one of these:
    # (See `discover_mihome.py` for `ask_fn` example)
    # These discovery types are defined in `energenie/__init__.py` (lines ~98-120) and `energenie/Registry.py` (lines 220 onwards).
    # TODO `discovery_auto()` was I think to blame for the registry file becoming almost 200 KiB within a day or two. Trying without it for now...
    #energenie.discovery_auto() # Auto-add unknown devices
    ##energenie.discovery_ask(ask_fn) # Asks for confirmation before adding unknown devices
    ##energenie.discovery_autojoin() # Looks for join requests and auto-adds
    ##energenie.discovery_askjoin(ask_fn) # Looks for join requests, then asks for confirmation before adding

    try:
        while True:
            energenie.loop()
            # time.sleep() was only used by the example script because it was toggling switches.
            # The `discover_mihome.py` example doesn't use time.sleep() at all.
            # Although `setup_tool.py`'s `do_mihome_discovery()` uses `time.sleep(0.25)`...
            #time.sleep(0.25)
            time.sleep(1)
            #time.sleep(APP_DELAY)

            #energy_monitor_loop()
    except KeyboardInterrupt:
        print("Interrupted. Exiting.", file=sys.stderr)
        exit(0)
    #except Exception as e:
        # `Exception` is the base class of all exceptions that we're "supposed"
        # to catch in most situations. It excludes KeyboardInterrupt, SystemExit,
        # GeneratorExit (which use BaseException instead).
    #    exit("Unexpected '{0}' error: {1}".format(type(e), e))
    finally:
        energenie.finished()

