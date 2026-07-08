from ctypes import *


#region import dll functions
CGHCalLib = cdll.LoadLibrary("cgh_lib.dll")

CoreInit = CGHCalLib.cgh_lib_init
CoreInit.restype = c_int

CoreCreate = CGHCalLib.cgh_core_create
CoreCreate.restype = c_int

CoreClose = CGHCalLib.cgh_core_close
CoreClose.restype = c_int
CoreClose.argtypes = [c_int]

CoreCalc = CGHCalLib.cgh_core_calc
CoreCalc.restype = c_int
CoreCalc.argtypes = [c_int,POINTER(c_ubyte),c_float]

CoreUpdateAll = CGHCalLib.cgh_core_update_all
CoreUpdateAll.restype = c_int
CoreUpdateAll.argtypes = [c_int,c_int,c_int,c_float,c_float,c_float]

ImageResize = CGHCalLib.cgh_image_resize
ImageResize.restype = c_int
ImageResize.argtypes = [POINTER(c_ubyte),c_int,c_int,POINTER(c_ubyte),c_int,c_int,c_int,c_ubyte]

def CghCoreInit():
    """ initilize cgh library.

    Returns: 
        SUCCESS: success; CGH_LIB_INIT_ERROR: initilize lib failed;
    """
    return CoreInit()


def CghCoreCreate():
    """ create cgh core before calculate.

    Returns: 
        SUCCESS: success; other number : failed.
    """
    return CoreCreate()

def CghCoreClose(hdl):
    """ close the created cgh core by hdl
    Args:
        hdl: handle of core
        
    Returns: 
        SUCCESS: success; other number : failed.
    """
    return CoreClose(hdl)

def CghCoreCalc(hdl,buffer,stroke_m):
    """ close the created cgh core by hdl
    Args:
        hdl: handle of core
        buffer: handle of core
        stroke_m: handle of core
       
    Returns: 
        SUCCESS: success; other number : failed.
    """
    ret=CoreCalc(hdl,buffer,stroke_m)
    return ret

def CghCoreUpdateAll(hdl, w_pixel, h_pixel, pix_size_m, distance, wavelenth):
    """ close the created cgh core by hdl
    Args:
        hdl: handle of core
        w_pixel: horizontal pixel number of LCD panel.
        h_pixel: vertical pixel number of LCD panel.
        pix_size_m: physical pixel size of LCD panel, unit meter.
        distance: focus distance, unit meter.
        wavelenth: wavelength of light, unit meter.
        
    Returns: 
        SUCCESS: success; other number : failed.
    """
    return CoreUpdateAll(hdl, w_pixel, h_pixel, pix_size_m, distance, wavelenth)

def CghImageResize(src_buf,src_width,src_height,dst_buf,dst_width,dst_height,mode,background_color):
    """ close the created cgh core by hdl
    Args:
        src_buf: piont of source 8 byte image buffer.
        src_width: width of source image.
        src_height: height of source image.
        dst_buf: piont of destination 8 byte image buffer.
        dst_width: width of destination image.
        dst_height: height of destination image.
        mode: resize mode
        background_color: set backgroud color for center/fill mode.
    Returns: 
        SUCCESS: success; other number : failed.
    """
 
    ret=ImageResize(src_buf,src_width,src_height,dst_buf,dst_width,dst_height,mode,background_color)

    return ret


