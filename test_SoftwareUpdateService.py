import pytest
import PQ9Client
from PQ9TestHelpers import getAddress
import sys
import struct
import math
import hashlib
import crc8
import json
import time

BLOCK_SIZE = 32
MD5_SIZE = 16
VERSION_SIZE = (8*2)

SERVICE_NUMBER = 18
PAYLOAD_SIZE_OFFSET = 3
ACKNOWLEDGE = 13

def OTAPreparation(destination, BinaryFiles):
    SourceFile = json.loads(BinaryFiles)[destination]
    stringData = SourceFile.split('_')
    VersionNumber = stringData[-2]
    SlotNumber = stringData[-1].split('.')[0]
    print("Source : "+stringData[0]+" | Version : "+VersionNumber+" | Slot : "+SlotNumber)
    fi = open(SourceFile, 'rb')
    foReq = open(SourceFile.strip('.bin') + ".pq9", 'w')
    foRep = open(SourceFile.strip('.bin') + ".pq9_response", 'w')

    # Get binary size by going through the file
    fi.seek(0, 2)
    size = fi.tell()
    print("Size : "+str(size))
    fi.seek(0, 0)
    iterations = math.floor(size / BLOCK_SIZE)
    rest = size % BLOCK_SIZE
    if (rest > 0):
        num_blocks = iterations + 1 
    else:
        num_blocks = iterations
    print("Number of Blocks: " +str(num_blocks))

    partials = num_blocks * [0]
    datablocks = num_blocks * [0]
    md5 = []
    
    #rewind file
    fi.seek(0,0)

    #create md5 coder
    m = hashlib.md5()

    temp = 0
    for i in range(0,iterations):
        #print("Processing block nr: "+str(i)+" | ", end="")  
        temp = fi.read(BLOCK_SIZE)
        datablocks[i] = temp
        m.update(temp)
        val = crc8.crc8()
        for q in temp:
            val.update(bytes([q]))
        crc = val.digest()
        #print(" - "+str(crc))
        partials[i] = crc

    if rest > 0:
        #print("Processing block nr: "+str(iterations)+" | ", end="")  
        temp = fi.read(rest)
        temp = temp + bytes((BLOCK_SIZE-rest)*[255])
        datablocks[iterations] = temp
        m.update(temp)
        val = crc8.crc8()
        for q in temp:
            val.update(bytes([q]))
        crc = val.digest()
        #print(" - "+str(crc))
        partials[iterations] = crc

    md5.append(m.digest())

    #rewind file
    fi.seek(0,0)

    md5 = md5[0]
    print("md5: " +str(md5))

    return fi, foReq, foRep, SlotNumber, md5, VersionNumber, num_blocks, partials, datablocks

def processOTACommand(payload, pq9_connection, destination, foReq, foRep, normalReply):
    command = {}
    command["_send_"] = "SendRaw"
    command["dest"] = getAddress(destination)
    command["src"] = getAddress('EGSE') 
    command["data"] = payload

    foReq.write(payload + "\n")
    succes, msg = pq9_connection.processCommand(command)
    assert succes == True, "Error: System is not responding"

    foRep.write(json.dumps(msg) + "\n")
    if normalReply != 'NoCheck':
        assert json.loads(msg['OTACommand'])['value'] == normalReply, "Error: Wrong response"

    return msg

def EraseSlot(pq9_connection, destination, foReq, foRep, SlotNumber):
    processOTACommand(str(SERVICE_NUMBER)+" 1 8 "+str(SlotNumber), pq9_connection, destination, foReq, foRep, 'NoCheck')
    processOTACommand(str(SERVICE_NUMBER)+" 1 8 13", pq9_connection, destination, foReq, foRep, 'Start')

def StartOTA(pq9_connection, destination, foReq, foRep, SlotNumber):
    processOTACommand(str(SERVICE_NUMBER)+" 1 0 "+SlotNumber, pq9_connection, destination, foReq, foRep, 'Start')

def SendMetaData(pq9_connection, destination, foReq, foRep, md5, VersionNumber, num_blocks):
    string = str(SERVICE_NUMBER)+" 1 1 "
    for i in range(0,MD5_SIZE):
        string += str(md5[i])
        string += " "
    for i in range(0,8):
        a = VersionNumber[2*i:(2*i)+2]
        string += str(int(a, 16))
        string += str(" ")

    vnum_bytes = struct.pack('>H', num_blocks)

    string += str(vnum_bytes[1])
    string += str(" ")
    string += str(vnum_bytes[0])
    processOTACommand(string, pq9_connection, destination, foReq, foRep, 'Start')

def SendCRC(pq9_connection, destination, foReq, foRep, num_blocks, partials):
    count = 0
    crcBlocks = math.floor(num_blocks/BLOCK_SIZE)
    for i in range(0,crcBlocks):
        string = str(SERVICE_NUMBER)+" 1 3 "
        count_bytes = struct.pack('>H', count)

        string += str(count_bytes[1])
        string += str(" ")
        string += str(count_bytes[0])
        string += str(" ")

        for j in range(0,BLOCK_SIZE):
            string += str((partials[BLOCK_SIZE*i+j][0] ))
            string += str(" ")
        processOTACommand(string, pq9_connection, destination, foReq, foRep, 'Start')
        count += BLOCK_SIZE

    if(num_blocks % BLOCK_SIZE > 0):
        string = str(SERVICE_NUMBER)+" 1 3 "
        count_bytes = struct.pack('>H', count)

        string += str(count_bytes[1])
        string += str(" ")
        string += str(count_bytes[0])
        string += str(" ")

        for j in range(0,num_blocks % BLOCK_SIZE):
            string += str((partials[BLOCK_SIZE*crcBlocks+j][0] ))
            string += str(" ")
        processOTACommand(string, pq9_connection, destination, foReq, foRep, 'Start')
        count += num_blocks % BLOCK_SIZE

def SendBlocks(pq9_connection, destination, foReq, foRep, num_blocks, datablocks):
    count = 0
    for i in range(0,num_blocks):
        string = str(SERVICE_NUMBER)+" 1 5 "
        count_bytes = struct.pack('>H', count)

        string += str(count_bytes[1])
        string += str(" ")
        string += str(count_bytes[0])
        string += str(" ")

        for j in range(0,BLOCK_SIZE):
            string += str((datablocks[i][j]))
            string += str(" ")
        processOTACommand(string, pq9_connection, destination, foReq, foRep, 'Start')
        count += 1

def StopOTA(pq9_connection, destination, foReq, foRep):
    processOTACommand(str(SERVICE_NUMBER)+" 1 7", pq9_connection, destination, foReq, foRep, 'Start')

def jumpSlot(pq9_connection, destination, slotNumber):
    command = {}
    command["_send_"] = "SendRaw"
    command["dest"] = getAddress(destination)
    command["src"] = getAddress('EGSE') 
    command["data"] = str(SERVICE_NUMBER)+" 1 9 "+str(slotNumber)+" 0"
    
    succes, msg = pq9_connection.processCommand(command)
    assert succes == True, "Error: System is not responding"

    return msg

def tryPing(pq9_connection, destination):
    command = {}
    command["_send_"] = "SendRaw"
    command["dest"] = getAddress(destination)
    command["src"] = getAddress('EGSE') 
    command["data"] = "17 1"
    
    succes, msg = pq9_connection.processCommand(command)

    return succes, msg

def getVersion(pq9_connection, destination):
    command = {}
    command["_send_"] = "SendRaw"
    command["dest"] = getAddress(destination)
    command["src"] = getAddress('EGSE') 
    command["data"] = "18 1 13"
    
    succes, msg = pq9_connection.processCommand(command)

    return succes, msg

def test_NormalSoftwareUpdate(pq9_connection, destination, BinaryFiles):
    time.sleep(0.5)
    fi, foReq, foRep, SlotNumber, md5, VersionNumber, num_blocks, partials, datablocks = OTAPreparation(destination, BinaryFiles)
    EraseSlot(pq9_connection, destination, foReq, foRep, SlotNumber)
    StartOTA(pq9_connection, destination, foReq, foRep, SlotNumber)
    SendMetaData(pq9_connection, destination, foReq, foRep, md5, VersionNumber, num_blocks)
    SendCRC(pq9_connection, destination, foReq, foRep, num_blocks, partials)
    SendBlocks(pq9_connection, destination, foReq, foRep, num_blocks, datablocks)
    StopOTA(pq9_connection, destination, foReq, foRep)

def test_SoftwareUpdateTime(pq9_connection, destination, BinaryFiles):
    time.sleep(0.5)
    # assumes last test was succesful and ping is succesful
    # Hence SLOT1 / SLOT2 is programmed with the target bin
    fi, foReq, foRep, SlotNumber, md5, VersionNumber, num_blocks, partials, datablocks = OTAPreparation(destination, BinaryFiles)
    
    #get version Number of target slot
    version = 8*[0]
    for i in range(0,8):
        version[i] = int(VersionNumber[i*2:(i+1)*2], 16)

    #ensure we are in SLOT0:
    jumpSlot(pq9_connection, destination, 0)
    time.sleep(0.5)

    #record time and Jump
    starttime = time.time()
    jumpSlot(pq9_connection, destination, 2)

    #wait for device to come alive
    succes = False
    while(not succes):
        succes, msg = tryPing(pq9_connection, destination)
        #print("try ping!")
    elapsedtime = time.time() - starttime

    #double check the version number
    succes, msg = getVersion(pq9_connection, destination)
    slotversion = (json.loads(msg['_raw_']))[6:14]
    print("Version of Bin: %s" % str(version))
    print("Version of SLOT: %s" % str(slotversion))
    print("Time till boot in slot: %.2f s" % elapsedtime)

    #make sure the jump was succesful and within 10seconds
    assert slotversion == version, "Bootloader jump not succesful"
    assert elapsedtime < 10, "Bootloader jump not fast enough!"

    #reset to slot0 for next tests
    jumpSlot(pq9_connection, destination, 0)
    time.sleep(0.5)

