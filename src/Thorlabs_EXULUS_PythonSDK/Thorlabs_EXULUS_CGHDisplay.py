from ctypes import *


#region import dll functions
CGHLib=cdll.LoadLibrary("cgh_display.dll")

GetMonitorCount=CGHLib.cgh_display_get_monitor_count
GetMonitorCount.restype = c_int

CreateWindow=CGHLib.cgh_display_create_window
CreateWindow.restype=c_int
CreateWindow.argtypes=[c_int,c_int,c_int,c_char_p]

SetWindowInfo=CGHLib.cgh_display_set_window_info
SetWindowInfo.restype=c_int
SetWindowInfo.argtypes=[c_int,c_int,c_int,c_byte]

ShowWindow=CGHLib.cgh_display_show_window
ShowWindow.restype=c_int
ShowWindow.argtypes=[c_int,POINTER(c_ubyte)]

CloseWindow=CGHLib.cgh_display_close_window
CloseWindow.restype=c_int
CloseWindow.argtypes=[c_int]


def CghDisplayGetMonitorCount():
    """ get enable monitor count for display

    Returns: 
        positive number: count of monitors; nagtive number : failed.
    """
    return GetMonitorCount()

def CghDisplayCreateWindow(monitor,width,height,title):
    """ create teh display window
    Args:
        monitor: monitor id, range is from 1 to count
        width: width of the window.
        height: height of the window
        title:title of the window.
    Returns: 
        non-negative number: hdl number returned successfully; negative number : failed.
    """
    return CreateWindow(monitor,width,height,title.encode('utf-8'))

def CghDisplaySetWindowInfo(window_handle,width,height,chan_num):
    """ set display window information
    Args:
        window_handle: handle of window
        width: width of the window.
        height: height of the window.
        chan_num:1: gray chanel; 3: RGB channel.
    Returns: 
        non-negative number: hdl number returned Successful; negative number: failed.
    """
    return SetWindowInfo(window_handle,width,height,chan_num)

def CghDisplayShowWindow(window_handle,imageBuffer):
    """ show window
    Args:
        window_handle: handle of window.
        buffer: display image buffer.
    Returns: 
        SUCCESS: success; other number : failed
    """
    return ShowWindow(window_handle,imageBuffer)

def CghDisplayCloseWindow(window_handle):
    """ close the created window by hdl
    Args:
        window_handle: handle of window
    Returns: 
        SUCCESS: success; other number : failed.
    """
    return CloseWindow(window_handle)




