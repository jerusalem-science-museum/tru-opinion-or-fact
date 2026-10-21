now let's make a simple app:
defaultly it shows the bg.jpg image. 
if we type in new<enter> then we get back to the terminal, where it asks you to put a new tag near the reader. 
when it recognizes it, it opens a dialogwindow to select first the "D" image (for dea - opinion) then the "U" image (uvda - fact).
it then saves that epc code to a dict and asks if you want to add any more rfids to the same images dict. offer a sixtet as default, i.e. 5 more after the initial one (but let the user also enter a different amount or skip completely, default by enter to have 5 more), so that many rfids can reference the same imgU and imgD. the exhibit will have a cube with a tag on each face, so we need 6 tags to be registered to the same imgU and imgD.
e.g.:
{
    "<epc1>": 
    {
        "imgU":"<path/to/img/U>",
        "imgD":"<path/to/img/D>"
    },
    "<epc2>": 
    {
        "imgU":"<path/to/img/U>",
        "imgD":"<path/to/img/D>"
    },
    ...
}
there might be a more concise way of doing this since many epcs point to the same imgU and imgD, offer a better solution if exists. the reason is that if a cube is lost, we want to be able to add a new cube with different epcs.
after offering to register the additional tags, ask if you want to register another cube with the same logic. 
if not, save the dict to some json file. that json should be loaded intially with the opening of the app. 

another part on startup should be getting the ids of our 2 rfid readers (using 
 s.write(bytes.fromhex('BB 00 03 00 01 00 04 7E'))  # get hardware version 
 or something similar). the ports should be recognizes automatically, assume they should be ch340 drivers or leonardo arduinos.
 then if those IDs aren't already in the config.json, we should be asked which one should be the D reader (dea, opinion) and which the U (uvda, fact). that info should be saved to the json and loaded as well next time we run the app.
now, when starting the program, when we put a tag near one of the readers, it should go to the dict and see the epc, if it exists show the corresponding img (imgU for U reader, imgD for D reader) for 10 seconds, then go back to bg.jpg.