try:
    from Thorlabs_EXULUS_CGHDisplay import *
except OSError as ex:
    print("Warning:",ex)
import time

def CommonFunc():
    hdl = CghDisplayCreateWindow(2,1920,1080,"SLM window")
    if(hdl < 0):
       print("Create window failed")
       return -1
    else:
       print("Current screen is 2")

  
    result=CghDisplaySetWindowInfo(hdl,1920,1080,1)
    if(result < 0):
       print("Set Window Info failed")
    else:
       print("Set Window Info successfully")

    Image=[255]*1920*1080    
    dstr=(c_ubyte*len(Image))(*Image)
    result = CghDisplayShowWindow(hdl,dstr)
    if(result < 0):
       print("Show failed")
    else:
       print("Show successfully")

    time.sleep(2)

    CghDisplayCloseWindow(hdl)



def main():
    print(" *** EXULUS CGH display python example *** ")

    try:
        count=CghDisplayGetMonitorCount()
        print(count)
        if(count <= 0):
           print('There is no devices connected')
        else:
           CommonFunc()
           
    except Exception as ex:
        print("Warning:",ex)
    print("*** End ***")
main()
input()
