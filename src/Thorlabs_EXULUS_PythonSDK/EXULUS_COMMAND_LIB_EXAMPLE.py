try:
    from EXULUS_COMMAND_LIB import *
except OSError as ex:
    print("Warning:",ex)


def CommonFunc(serialNumber):
    hdl = EXULUSOpen(serialNumber,38400,3)
    if(hdl < 0):
       print("Connect ",serialNumber, "fail")
       return -1
    else:
       print("Connect ",serialNumber, "successfully")

    result = EXULUSIsOpen(serialNumber)
    if(result < 0):
       print("Open failed ")
    else:
       print("EXULUS is open ")
    
    print("-----------------Get EXULUS device information----------------")
    code=[0]
    codeList={6:"Acknowledge", 9:"Not Acknowledge", 187:"SPI_Busy"}
    result=EXULUSCheckCommunication(hdl,code) 
    if(result < 0):
       print("Get device parameters failed ")
    else:
       print("Device parameters: ", codeList.get(code[0]))    

       

    print("-----------------Get/Set EXULUS device data----------------") 



    result = EXULUSSetScreenHorizontalFlip(hdl,1) #0: Flip in Horizontal Off;1: Flip in Horizontal On
    if(result < 0):
       print("Set Screen Horizontal Flip failed ")
    else:
       print("Set Screen Horizontal Flip : On",)

    x = [0]
    result = EXULUSGetScreenHorizontalFlip(hdl,x)
    if(result < 0):
       print("Get Screen Horizontal Flip failed ")
    else:
      if(x[0]==1):
           print("Screen Horizontal Flip : On")
      else:
           print("Screen Horizontal Flip : Off")

    result = EXULUSSetScreenVerticalFlip(hdl,1) # 0: Flip in Vertical Off;1: Flip in Vertical On;
    if(result < 0):
       print("Set Screen Vertical Flip failed ")
    else:
       print("Set Screen Vertical Flip On")

    y = [0]
    result = EXULUSGetScreenVerticalFlip(hdl,y)
    if(result < 0):
       print("Get Screen Vertical Flip failed ")
    else:
       if(y[0]==1):
           print("Screen Vertical Flip is : On")
       else:
           print("Screen Vertical Flip is : Off")



    result = EXULUSSetPhaseStrokeMode(hdl,1) #0: Full Wave;1: Half Wave;
    if(result < 0):
       print("Set Phase Stroke Mode failed")
    else:
       print("Set Phase Stroke Mode: Half Wave")

    tl = [0]
    result = EXULUSGetPhaseStrokeMode(hdl,tl)
    if(result < 0):
       print("Get Phase Stroke Mode failed ")
    else:
       if(tl[0]==1):
           print("Phase Stroke Mode : Half Wave")
       else:
           print("Phase Stroke Mode : Full Wave")


    result = EXULUSSetTestPatternStatus(hdl,1) #0: Test Pattern Off;1: Test Pattern On;
    if(result < 0):
       print("Set Test Pattern Status failed ")
    else:
       print("Set Test Pattern Status On")

    gs = [0]
    result = EXULUSGetTestPatternStatus(hdl,gs)
    if(result < 0):
       print("Get Test Pattern Status failed ")
    else:
       if(gs[0]==1):
           print("Test Pattern Status is : On")
       else:
           print("Test Pattern Status is : Off")

    EXULUSClose(hdl)

def main():
    print(" *** EXULUS device python example *** ")
    try:
        devs = EXULUSListDevices()
        print(devs)
        if(len(devs) <= 0):
           print('There is no devices connected')
        else:
           EXULUS = devs[0]
           CommonFunc(EXULUS[0])
           
    except Exception as ex:
        print("Warning:",ex)
    print("*** End ***")
main()

input()