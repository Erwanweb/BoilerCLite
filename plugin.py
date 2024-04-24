"""
Easily control boiler from heating request from multi zone SVT TRV python plugin for Domoticz
Author: Erwanweb,
Version:    0.0.1: alpha
            0.0.2: beta
            0.1.1: correction timer on
            0.1.2: correction for resending order to device
"""
"""
<plugin key="BoilerCLite" name="AC Boiler control LITE" author="Erwanweb" version="0.1.2" externallink="https://github.com/Erwanweb/BoilerCLite.git">
    <description>
        <h2>Boiler control for SVT TRV</h2><br/>
        V.0.1.2<br/>
        Easily control boiler from heating request from multi zone SVT TRV<br/>
        <h3>Set-up and Configuration</h3>
    </description>
    <params>
        <param field="Address" label="Domoticz IP Address" width="200px" required="true" default="127.0.0.1"/>
        <param field="Port" label="Port" width="40px" required="true" default="8080"/>
        <param field="Username" label="Username" width="200px" required="false" default=""/>
        <param field="Password" label="Password" width="200px" required="false" default=""/>
        <param field="Mode1" label="Heating request switches (csv list of idx)" width="100px" required="true" default=""/>
        <param field="Mode5" label="Delay : On, order confirm. (all in minutes)" width="200px" required="true" default="10,60"/>
        <param field="Mode2" label="Heating switch for boiler control (csv list of idx)" width="100px" required="true" default=""/>
        <param field="Mode6" label="Logging Level" width="200px">
            <options>
                <option label="Normal" value="Normal"  default="true"/>
                <option label="Verbose" value="Verbose"/>
                <option label="Debug - Python Only" value="2"/>
                <option label="Debug - Basic" value="62"/>
                <option label="Debug - Basic+Messages" value="126"/>
                <option label="Debug - Connections Only" value="16"/>
                <option label="Debug - Connections+Queue" value="144"/>
                <option label="Debug - All" value="-1"/>
            </options>
        </param>
    </params>
</plugin>
"""
import Domoticz
import json
import urllib.parse as parse
import urllib.request as request
from datetime import datetime, timedelta
import time
import base64
import itertools

class deviceparam:

    def __init__(self, unit, nvalue, svalue):
        self.unit = unit
        self.nvalue = nvalue
        self.svalue = svalue


class BasePlugin:

    def __init__(self):

        self.debug = False
        self.ondelay = 10
        self.orderconfirm = 60
        self.Heatingrequester = []
        self.Heaters = []
        self.Heat = False
        self.Heatingrequested = False
        self.Heatingrequestchangedtime = datetime.now()
        self.Heatingorderchangedtime = datetime.now()
        self.Heatingrequestregistred = True
        self.loglevel = None
        self.statussupported = True
        return


    def onStart(self):

        # setup the appropriate logging level
        try:
            debuglevel = int(Parameters["Mode6"])
        except ValueError:
            debuglevel = 0
            self.loglevel = Parameters["Mode6"]
        if debuglevel != 0:
            self.debug = True
            Domoticz.Debugging(debuglevel)
            DumpConfigToLog()
            self.loglevel = "Verbose"
        else:
            self.debug = False
            Domoticz.Debugging(0)

        # create the child devices if these do not exist yet
        devicecreated = []
        if 1 not in Devices:
            Options = {"LevelActions": "||",
                       "LevelNames": "Off|Auto",
                       "LevelOffHidden": "false",
                       "SelectorStyle": "0"}
            Domoticz.Device(Name="Control", Unit=1, TypeName="Selector Switch", Switchtype=18, Image=15,
                            Options=Options, Used=1).Create()
            devicecreated.append(deviceparam(1, 0, "0"))  # default is Off state
        if 2 not in Devices:
            Domoticz.Device(Name="General heating request", Unit=2, TypeName="Switch", Image=9, Used=1).Create()
            devicecreated.append(deviceparam(2, 0, ""))  # default is Off

        # if any device has been created in onStart(), now is time to update its defaults
        for device in devicecreated:
            Devices[device.unit].Update(nValue=device.nvalue, sValue=device.svalue)

        # build lists of sensors and switches
        self.Heatingrequester = parseCSV(Parameters["Mode1"])
        Domoticz.Debug("Heating requester = {}".format(self.Heatingrequester))
        self.Heaters = parseCSV(Parameters["Mode2"])
        Domoticz.Debug("Heaters = {}".format(self.Heaters))

        # splits additional parameters
        params = parseCSV(Parameters["Mode5"])
        if len(params) == 2:
            self.ondelay = CheckParam("On Delay",params[0],10)
            if self.ondelay < 5:
                Domoticz.Error("Invalid on delay parameter. Using minimum of 5 minutes !")
                self.ondelay = 5
            self.orderconfirm = CheckParam("order confirmation Delay",params[1],60)
            if self.orderconfirm < 15:
                Domoticz.Error("Invalid forced order confirmation parameter. Using minimum of 15 minutes !")
                self.orderconfirm = 15

        else:
            Domoticz.Error("Error reading Mode5 parameters")

        # if mode = off then make sure actual heating is off just in case if was manually set to on
        if Devices[1].sValue == "0":
            self.SwitchHeat(False)


    def onStop(self):

        Domoticz.Debugging(0)


    def onCommand(self, Unit, Command, Level, Color):

        Domoticz.Debug("onCommand called for Unit {}: Command '{}', Level: {}".format(Unit, Command, Level))

        if Unit == 1:  # Boiler control
            nvalue = 1 if Level > 0 else 0
            svalue = str(Level)
            self.onHeartbeat()

        Devices[Unit].Update(nValue=nvalue, sValue=svalue)


    def onHeartbeat(self):

        # fool proof checking.... based on users feedback
        if not all(device in Devices for device in (1,2)):
            Domoticz.Error("one or more devices required by the plugin is/are missing, please check domoticz device creation settings and restart !")
            return

        if Devices[1].sValue == "0":  # Boiler is off
            Domoticz.Log("Control is OFF")
            if self.Heat:  # thermostat setting was just changed so we kill the heating
                self.Heat = False
                self.Heatingrequested = False
                Domoticz.Debug("Switching heat Off !")
                self.SwitchHeat(False)
                if Devices[2].nValue == 1:
                   Devices[2].Update(nValue = 0,sValue = Devices[2].sValue)
        else:
            self.Heatingrequest()
            Domoticz.Log("Control is in AUTO mode")


    def Heatingrequest(self):

        now = datetime.now()

        if Devices[1].sValue == "10":  # Auto mode is on
             self.Heatingrequested = False
             # Build list of Heating requester device, with their current status
             Heatingrequesterswitch = {}
             devicesAPI = DomoticzAPI("type=command&param=getdevices&filter=light&used=true&order=Name")
             if devicesAPI:
                for device in devicesAPI["result"]:  # parse the Heating requester device
                    idx = int(device["idx"])
                    if idx in self.Heatingrequester:  # this is one of our Heating requester switch
                        if "Status" in device:
                            Heatingrequesterswitch[idx] = True if device["Status"] == "On" else False
                            Domoticz.Debug("Heating request switch {} currently is '{}'".format(idx,device["Status"]))
                            if device["Status"] == "On":
                                self.Heatingrequested = True

                        else:
                            Domoticz.Error("Device with idx={} does not seem to be a Heating request switch !".format(idx))


             # fool proof checking....
             if len(Heatingrequesterswitch) == 0:
                Domoticz.Error("none of the devices in the 'Heating request switch' parameter is a switch... no action !")
                self.Heatingrequested = False
                self.Heat = False
                Devices[2].Update(nValue = 0,sValue = Devices[2].sValue)
                return

             if self.Heatingrequested:
                if Devices[2].nValue == 1:
                    Domoticz.Debug("Heating requested but already registred...")
                    self.Heat = True
                    self.SwitchHeat(True)
                else:
                    if not self.Heatingrequestregistred:
                        Domoticz.Debug("Heating is just now requested... Timer on")
                        self.Heatingrequestregistred = True
                        self.Heatingrequestchangedtime = datetime.now()
                    else:
                        if self.Heatingrequestchangedtime + timedelta(minutes=self.ondelay) < now:
                            Domoticz.Debug("Heating requested - Timer on passed - ON !")
                            Devices[2].Update(nValue = 1,sValue = Devices[2].sValue)
                            self.Heat = True
                            self.SwitchHeat(True)
                        else:
                            Domoticz.Debug("Heating requested - under timer on period")


             else:
                Domoticz.Debug("No heating requested")
                self.Heat = False
                self.SwitchHeat(False)
                if Devices[2].nValue == 1:
                    Devices[2].Update(nValue = 0,sValue = Devices[2].sValue)




    def SwitchHeat(self, switch):

        now = datetime.now()

        # Build list of heater switches, with their current status,
        # to be used to check if any of the heaters is already in desired state
        switches = {}
        devicesAPI = DomoticzAPI("type=command&param=getdevices&filter=light&used=true&order=Name")
        if devicesAPI:
            for device in devicesAPI["result"]:  # parse the switch device
                idx = int(device["idx"])
                if idx in self.Heaters:  # this switch is one of our heaters
                    if "Status" in device:
                        switches[idx] = True if device["Status"] == "On" else False
                        Domoticz.Debug("Heater switch {} currently is '{}'".format(idx, device["Status"]))
                    else:
                        Domoticz.Error("Device with idx={} does not seem to be a switch !".format(idx))

        # fool proof checking.... based on users feedback
        if len(switches) == 0:
            Domoticz.Error("none of the devices in the 'heaters' parameter is a switch... no action !")
            return

        # flip on / off as needed
        self.Heat = switch
        command = "On" if switch else "Off"
        Domoticz.Debug("Heating '{}'".format(command))
        for idx in self.Heaters:
            if switches[idx] != switch:  # check if action needed
                DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd={}".format(idx, command))
                self.Heatingorderchangedtime = datetime.now()
        if self.Heatingorderchangedtime + timedelta(minutes=self.orderconfirm) < now: # be sure each hour heater take the real good order and position
            self.Heatingorderchangedtime = datetime.now()
            for idx in self.Heaters:
                DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd={}".format(idx,command))

        if switch:
            Domoticz.Debug("Heating requested at Boiler")



    def WriteLog(self, message, level="Normal"):

        if self.loglevel == "Verbose" and level == "Verbose":
            Domoticz.Log(message)
        elif level == "Normal":
            Domoticz.Log(message)



global _plugin
_plugin = BasePlugin()


def onStart():
    global _plugin
    _plugin.onStart()


def onStop():
    global _plugin
    _plugin.onStop()


def onCommand(Unit, Command, Level, Color):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Color)


def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()


# Plugin utility functions ---------------------------------------------------

def parseCSV(strCSV):

    listvals = []
    for value in strCSV.split(","):
        try:
            val = int(value)
        except:
            pass
        else:
            listvals.append(val)
    return listvals


def DomoticzAPI(APICall):

    resultJson = None
    url = "http://{}:{}/json.htm?{}".format(Parameters["Address"], Parameters["Port"], parse.quote(APICall, safe="&="))
    Domoticz.Debug("Calling domoticz API: {}".format(url))
    try:
        req = request.Request(url)
        if Parameters["Username"] != "":
            Domoticz.Debug("Add authentification for user {}".format(Parameters["Username"]))
            credentials = ('%s:%s' % (Parameters["Username"], Parameters["Password"]))
            encoded_credentials = base64.b64encode(credentials.encode('ascii'))
            req.add_header('Authorization', 'Basic %s' % encoded_credentials.decode("ascii"))

        response = request.urlopen(req)
        if response.status == 200:
            resultJson = json.loads(response.read().decode('utf-8'))
            if resultJson["status"] != "OK":
                Domoticz.Error("Domoticz API returned an error: status = {}".format(resultJson["status"]))
                resultJson = None
        else:
            Domoticz.Error("Domoticz API: http error = {}".format(response.status))
    except:
        Domoticz.Error("Error calling '{}'".format(url))
    return resultJson


def CheckParam(name, value, default):

    try:
        param = int(value)
    except ValueError:
        param = default
        Domoticz.Error("Parameter '{}' has an invalid value of '{}' ! defaut of '{}' is instead used.".format(name, value, default))
    return param


# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug("'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return
