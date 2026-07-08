try:
    from Thorlabs_EXULUS_CGHCalculate import *
except OSError as ex:
    print("Warning:",ex)
import cv2 as cv
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
import tkinter as tk
from tkinter import filedialog

 
def main():
    print(" *** EXULUS CGH calculate python example *** ")
    screenWidth=1920
    screenHeight=1080

    try:
        root = tk.Tk()
        root.withdraw()

        Filepath=filedialog.askopenfilename(title='Please choose an image')
        print('Filepath',Filepath)
        img = cv.imread(Filepath)
        img0 = cv.cvtColor(img,cv.COLOR_BGR2GRAY)
        cv.imshow("Image",img0)
        cv.waitKey(0)
        
        sp=img0.shape
        imageHeight=sp[0]
        imageWidth=sp[1]
        flatGray = img0.flatten()
        nsrcr=(c_ubyte * len(flatGray))(*flatGray)


        dst=[0]*screenWidth*screenHeight
        dstr=(c_ubyte*len(dst))(*dst)


        result = CghImageResize(nsrcr,imageWidth,imageHeight,dstr,screenWidth,screenHeight,0,255)
        print(dstr)
        if(result < 0):
          print('Image resize failed')
        else:
          print('Image resize succeed')

        result=CghCoreInit()
        if(result < 0):
          print('Init failed')
        else:
          print('Init finished')

        hdl=CghCoreCreate()
        if(result < 0):
          print('Core Create failed')
        else:
          print('Core Create finished')

        result=CghCoreUpdateAll(hdl,screenWidth,screenHeight,0.0000064,0.00000155,0.25)
        if(result < 0):
          print('Update parameters failed')
        else:
          print('Update parameters succeed')

        result=CghCoreCalc(hdl,dstr,0.000005162)
        if(result < 0):
          print('Calculate CGH failed')
        else:
          print('Calcculate CGH finished')

        flatNumpyArray=np.array(dstr)
        grayImage = flatNumpyArray.reshape(screenHeight, screenWidth)
        cv.imshow('GrayImage', grayImage)
        print(grayImage)
        cv.waitKey(0)

        result=CghCoreClose(hdl)
        if(result < 0):
          print('Close failed')
        else:
          print('Handle closed')
         
           
    except Exception as ex:
        print("Warning:",ex)
    print("*** End ***")
main()
input()