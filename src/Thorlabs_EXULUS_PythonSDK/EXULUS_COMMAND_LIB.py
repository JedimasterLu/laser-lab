from ctypes import *


#region import dll functions
EXULUSLib=cdll.LoadLibrary("exulus_command_library.dll")

"""comman command
"""
List = EXULUSLib.list
List.restype = c_int
List.argtypes = [c_char_p,c_int]

Open = EXULUSLib.open
Open.restype = c_int
Open.argtypes = [c_char_p,c_int,c_int]

IsOpen = EXULUSLib.is_open
IsOpen.restype = c_int
IsOpen.argtypes = [c_char_p]

Close = EXULUSLib.close
Close.restype = c_int
Close.argtypes = [c_int]

SetTimeout=EXULUSLib.set_timeout
SetTimeout.restype = c_int
SetTimeout.argtypes = [c_int,c_int]
"""device command
"""


CheckCommunication=EXULUSLib.check_communication
CheckCommunication.restype = c_int
CheckCommunication.argtypes=[c_int,POINTER(c_ubyte)]


GetScreenHorizontalFlip= EXULUSLib.get_screen_horizontal_flip
GetScreenHorizontalFlip.restype=c_int
GetScreenHorizontalFlip.argtypes=[c_int,POINTER(c_ubyte)]

SetScreenHorizontalFlip=EXULUSLib.set_screen_horizontal_flip
SetScreenHorizontalFlip.restype=c_int
SetScreenHorizontalFlip.argtypes=[c_int,c_ubyte]

GetScreenVerticalFlip=EXULUSLib.get_screen_vertical_flip
GetScreenVerticalFlip.restype=c_int
GetScreenVerticalFlip.argtypes=[c_int,POINTER(c_ubyte)]

SetScreenVerticalFlip=EXULUSLib.set_screen_vertical_flip
SetScreenVerticalFlip.restype=c_int
SetScreenVerticalFlip.argtypes=[c_int,c_ubyte]


GetPhaseStrokeMode=EXULUSLib.get_phase_stroke_mode
GetPhaseStrokeMode.restype=c_int
GetPhaseStrokeMode.argtypes=[c_int,POINTER(c_ubyte)]

SetPhaseStrokeMode=EXULUSLib.set_phase_stroke_mode
SetPhaseStrokeMode.restype=c_int
SetPhaseStrokeMode.argtypes=[c_int,c_ubyte]

GetTestPatternStatus=EXULUSLib.get_test_pattern_status
GetTestPatternStatus.restype=c_int
GetTestPatternStatus.argtypes=[c_int,POINTER(c_ubyte)]

SetTestPatternStatus=EXULUSLib.set_test_pattern_status
SetTestPatternStatus.restype=c_int
SetTestPatternStatus.argtypes=[c_int,c_ubyte]

SaveDefaultSetting=EXULUSLib.save_default_setting
SaveDefaultSetting.restype=c_int
SaveDefaultSetting.argtypes=[c_int]


#region command for EXULUS
def EXULUSListDevices():
    """ List all connected EXULUS devices
    Returns: 
       The EXULUS device list, each deice item is [serialNumber, EXULUSType]
    """
    str = create_string_buffer(1024, '\0')
    result = List(str,1024)
    devicesStr = str.raw.decode("utf-8").rstrip('\x00').split(',')
    length = len(devicesStr)
    i = 0
    devices = []
    devInfo = ["",""]
    while(i < length):
        str = devicesStr[i]
        if (i % 2 == 0):
            if str != '':
                devInfo[0] = str
            else:
                i+=1
        else:
                if(str.find("EXULUS") >= 0):
                    isFind = True
                devInfo[1] = str
                devices.append(devInfo.copy())
        i+=1
    return devices

def EXULUSOpen(serialNo, nBaud, timeout):
    """ Open EXULUS device
    Args:
        serialNo: serial number of EXULUS device
        nBaud: bit per second of port
        timeout: set timeout value in (s)
    Returns: 
        non-negative number: hdl number returned Successful; negative number: failed.
    """
    return Open(serialNo.encode('utf-8'), nBaud, timeout)

def EXULUSIsOpen(serialNo):
    """ Check opened status of EXULUS device
    Args:
        serialNo: serial number of EXULUS device
    Returns: 
        0: EXULUS device is not opened; 1: EXULUS device is opened.
    """
    return IsOpen(serialNo.encode('utf-8'))


def EXULUSClose(hdl):
    """ Close opened EXULUS device
    Args:
        hdl: the handle of opened EXULUS device
    Returns: 
        0: Success; negative number: failed.
    """
    return Close(hdl)




def EXULUSCheckCommunication(hdl,value):
    """ Check if the device communication is ok.
    Args:
        hdl: the handle of opened EXULUS device
        ack_code: Acknowledge (0x06), Not Acknowledge (0x09), SPI_Busy (0xBB)
    Returns: 
        0: Success; negative number: failed; 0xEB: time out; 0xED: invalid string buffer;
    """
    code = c_ubyte(0)
    ret=CheckCommunication(hdl,code)
    value[0]=code.value

    return ret


def EXULUSGetScreenHorizontalFlip(hdl,value):
    """ Get Image Horizontal Flip.
    Args:
        hdl: the handle of opened EXULUS device
        flip: 0x00: Flip in Horizontal Off;0x01: Flip in Horizontal On
    Returns: 
        0: Success; negative number: failed; 0xEB: time out; 0xED: invalid string buffer;
    """
    flip = c_ubyte(0)
    ret=GetScreenHorizontalFlip(hdl,flip)
    value[0]=flip.value

    return ret


def EXULUSSetScreenHorizontalFlip(hdl,value):
    """ Set Image Horizontal Flip.
    Args:
        hdl: the handle of opened EXULUS device
        flip: 0x00: Flip in Horizontal Off;0x01: Flip in Horizontal On
    Returns:
        0: Success; negative number: failed; 0xEB: time out; 0xED: invalid string buffer;
    """
    return SetScreenHorizontalFlip(hdl,value)

def EXULUSGetScreenVerticalFlip(hdl,value):
    """ Get Image Vertical Flip.
    Args:
        hdl: the handle of opened EXULUS device
        flip: 0x00: Flip in Vertical Off;0x01: Flip in Vertical On;
    Returns: 
        0: Success; negative number: failed; 0xEB: time out; 0xED: invalid string buffer;
    """
    flip = c_ubyte(0)
    ret=GetScreenVerticalFlip(hdl,flip)
    value[0]=flip.value

    return ret

def EXULUSSetScreenVerticalFlip(hdl,value):
    """ Set Image Vertical Flip.
    Args:
        hdl: the handle of opened EXULUS device
        flip: 0x00: Flip in Vertical Off;0x01: Flip in Vertical On;
    Returns: 
        0: Success; negative number: failed; 0xEB: time out; 0xED: invalid string buffer;
    """
    return SetScreenVerticalFlip(hdl,value)



def EXULUSGetPhaseStrokeMode(hdl,value):
    """ Set Gamma Table Location.
    Args:
        hdl: the handle of opened EXULUS device
        Gamma Table Location:: 0x00: #1 Gamma Table;0x01: #2 Gamma Table
    Returns: 
        0: Success; negative number: failed; 0xEB: time out; 0xED: invalid string buffer;
    """
    loc = c_ubyte(0)
    ret=GetPhaseStrokeMode(hdl,loc)
    value[0]=loc.value

    return ret

def EXULUSSetPhaseStrokeMode(hdl,value):
    """ Get Internal Pattern Generator Status.
    Args:
        hdl: the handle of opened EXULUS device
        status: 0x00: Internal Pattern Generator Off;0x01: Internal Pattern Generator On;
    Returns: 
        0: Success; negative number: failed; 0xEB: time out; 0xED: invalid string buffer;
    """
    return SetPhaseStrokeMode(hdl,value)

def EXULUSGetTestPatternStatus(hdl,value):
    """ Set Internal Pattern Generator Status.
    Args:
        hdl: the handle of opened EXULUS device
        status: 0x00: Internal Pattern Generator Off;0x01: Internal Pattern Generator On;
    Returns: 
        0: Success; negative number: failed; 0xEB: time out; 0xED: invalid string buffer;
    """
    sta = c_ubyte(0)
    ret=GetTestPatternStatus(hdl,sta)
    value[0]=sta.value
    
    return ret

def EXULUSSetTestPatternStatus(hdl,value):
    """ Set Internal Pattern Generator Status.
    Args:
        hdl: the handle of opened EXULUS device
        status: 0x00: Internal Pattern Generator Off;0x01: Internal Pattern Generator On;
    Returns: 
        0: Success; negative number: failed; 0xEB: time out; 0xED: invalid string buffer;
    """
    return SetTestPatternStatus(hdl,value)

def EXULUSSaveDefaultSetting(hdl,value):
    """ Save System Parameters to EEPROM
    Args:
        hdl: the handle of opened EXULUS device
    Returns: 
        0: Success; negative number: failed; 0xEB: time out; 0xED: invalid string buffer;
    """
    return SaveDefaultSetting(hdl,value)
