import re
import sys
import os
import pandas as pd
from functools import cache
import json
import numpy as np

import timeit # for timing the code

# In the replay file the table starts with the following bytes
START_OF_TABLE = [0x01, 0x16, 0xC6, 0x01]
TABLE_HEADER_SIZE = 211 # The size of the header of the table in bytes
END_OF_PLAYERS_SECTION = [0x00, 0x00, 0x00, 0x00]
START_OF_SCORES_SECTION = [0x03, 0x00, 0x00, 0x01]

START_OF_MESSAGE_SECTION = [0x02, 0x58, 0x74, 0xF0]
END_OF_MESSAGE_SECTION = [0x11, 0x01]

# Score table delimination
# There's some more stuff like damageZone and awardDamage but I stopped with this before I figured that out
ROW_SIZE = 152
AIR_KILLS = 16
GROUND_KILLS = 24
NAVAL_KILLS = 32
TEAM_KILLS = 40
AI_AIR_KILLS = 48
AI_GROUND_KILLS = 56
AI_NAVAL_KILLS = 64
ASSISTS = 72
DEATHS = 80 #83
CAPTURES = 88
SQUAD = 128
AUTO_SQUAD = 136
TEAM = 144
DAMAGE_ZONE = [96, 97]
SCORE = [104,105]
AWARD_DAMAGE = [110, 111]

PLAYER_ID_OFFSET = -1
VEHICLE_NAME_LENGTH = 6
VEHICLE_NAME_START = 7

def timeFunction(function, *args):
    start = timeit.default_timer()
    returns = function(*args)
    end = timeit.default_timer()
    print(f"Time Taken: {end - start:.10f}s")
    return returns

def timeStart():
    return timeit.default_timer()

def timeEnd(start):
    end = timeit.default_timer()
    print(f"Time Taken: {end - start:.10f}s")

def get_players(playersTable):
    # Each player has 2 or 3 sections (depending on if they have a clan tag), delimited by 0x00
    # Each player always has an ID so we need to split on that
    # b'Player Name' b'-CLAN TAG-' b'ID'
    # the ID is always just numbers
    
    # Split the table on \x00
    splitTable = playersTable.split(b'\x00')
    # Reverse the list as its easier to split on the ID
    splitTable.reverse()

    players = dict()

    playerIndex = 0
    for i, entry in enumerate(splitTable):
        if entry.isdigit():
            # This is an ID
            ID = int(entry.decode("utf-8"))
            clanTag = None
            # If the 2nd next entry is not a digit then this player has a clan tag
            if not splitTable[i+2].isdigit():
                # The next entry is the clan tag
                clanTag = splitTable[i+1].decode("utf-8")
                # The next entry is the name
                name = splitTable[i+2].decode("utf-8")
            else:
                # The next entry is the name
                name = splitTable[i+1].decode("utf-8")
            # Add the player to the dict
            players[ID] = {"ID" :ID, "name":name, "clanTag":clanTag, "index":playerIndex}
            playerIndex += 1
    # Because we reversed the list we need to reverse player indexs'
    for player in players.values():
        player["index"] = playerIndex - player["index"] - 1
    return players


def get_scores(scoresTable, players):
    # Split the table into rows of ROW_SIZE bytes
    splitTable = [scoresTable[i:i+ROW_SIZE] for i in range(0, len(scoresTable), ROW_SIZE)]

    # Remove rows that are not players
    splitTable = splitTable[:len(players)]

    # Each Row is a player
    for i,row in enumerate(splitTable):
        # find the player ID from the index
        for ID, player in players.items():
            if player["index"] == i:
                break

        players[ID]["airKills"] = int.from_bytes(row[AIR_KILLS:AIR_KILLS+4], byteorder="little")
        players[ID]["groundKills"] = int.from_bytes(row[GROUND_KILLS:GROUND_KILLS+4], byteorder="little")
        players[ID]["navalKills"] = int.from_bytes(row[NAVAL_KILLS:NAVAL_KILLS+4], byteorder="little")
        players[ID]["teamKills"] = int.from_bytes(row[TEAM_KILLS:TEAM_KILLS+4], byteorder="little")
        players[ID]["aiAirKills"] = int.from_bytes(row[AI_AIR_KILLS:AI_AIR_KILLS+4], byteorder="little")
        players[ID]["aiGroundKills"] = int.from_bytes(row[AI_GROUND_KILLS:AI_GROUND_KILLS+4], byteorder="little")
        players[ID]["aiNavalKills"] = int.from_bytes(row[AI_NAVAL_KILLS:AI_NAVAL_KILLS+4], byteorder="little")
        players[ID]["assists"] = row[ASSISTS]
        players[ID]["deaths"] = row[DEATHS]
        players[ID]["captures"] = row[CAPTURES]
        try:
            players[ID]["squad"] = row[SQUAD]
        except:
            # idk I forgot
            continue
        players[ID]["autoSquad"] = row[AUTO_SQUAD]
        players[ID]["team"] = row[TEAM]
        players[ID]["score"] = row[SCORE[0]] + row[SCORE[1]]*256
    return players

@cache
def lookup_nation(vehicleName):
    # For speed we first just check if the nation is present in the name
    nations = {
        "us_" : "USA",
        "ussr_" : "USSR",
        "germ_" : "Germany",
        "uk_" : "Great Britain",
        "jp_" : "Japan",
        "it_" : "Italy",
        "fr_" : "France",
        "cn_" : "China",
        "sw_" : "Sweden",
        "il_" : "Israel",
        }

    for nation in nations:
        if nation == vehicleName[:len(nation)]:
            return nations[nation]

    # If we couldn't find the nation in the name, we need to look it up

    # Read in the lookup.txt
    with open("lookup.txt", "r", encoding="utf-8") as f:
        lookup = f.read()
    
    # Find index of vehicle name
    vehicleNameIndex = lookup.find(vehicleName)

    # If the vehicle name is not found, return None
    if vehicleNameIndex == -1:
        return None
    
    # Once the vehicle name is found, index back to the nation
    # Nation is a like similar to "==== Great Britain ===="
    endOfNationIndex = lookup.rfind("====", 0, vehicleNameIndex)

    # Nation is the string between the last ==== and the next ====
    startOfNationIndex = lookup.rfind("====", 0, endOfNationIndex-1) + 4
    nation = lookup[startOfNationIndex:endOfNationIndex-1]
    # If nations is allowed, return the nation
    if nation not in ['drones', 'Nuclear bombers', 'Special']:
        return nation
    return None

def find_byte_sequence(data, pattern):
    occurrences = []
    pattern_length = len(pattern)
    data_length = len(data)

    for i in range(data_length - pattern_length + 1):
        match = True
        for j in range(pattern_length):
            if pattern[j] != b'.'[0] and data[i+j] != pattern[j]:
                match = False
                break
        if match:
            occurrences.append(i)

    return occurrences

def get_messages(data, players):
    # Search for occurences of the following bytes
    # Use a raw string and escape the dots to match any byte

    # This was the old lookup
    # lookup = b'\xFF........\x00'

    # This is the new one, not ideal as it's a lot slower but it works
    # This will also retrieve vehicle ids (like us_m19)
    # I have countered this by using the units.csv from the datamines to match these and remove them
    # I have this implemented in the javascript version of this script, that's why I'm not doing it here
    lookup = b'...\x00'

    # Find all occurences
    occurrences = [m.start() for m in re.finditer(lookup, data, re.DOTALL)]

    messages = []
    for start in occurrences:
        try:
            # player name length byte is 1 byte after the occurrence
            playerNameLength = data[start + len(lookup)]
            
            # Extract player name
            nameStart = start + len(lookup) + 1
            playerName = data[nameStart:nameStart+playerNameLength].decode('utf-8', errors='ignore')

            for ID, player in players.items():
                if player["name"] == playerName:
                    # Find message length
                    messageStart = nameStart + playerNameLength
                    messageLengthByte = data[messageStart]
                    
                    # Extract message
                    messageStart += 1
                    message = data[messageStart:messageStart+messageLengthByte].decode('utf-8', errors='ignore')

                    # Check if it is "all", "team", or "squad" chat
                    if messageStart + messageLengthByte < len(data):  # Ensure we don't go out of bounds
                        chatTypeByte = data[messageStart + messageLengthByte]
                        if chatTypeByte == 1:
                            chatType = "all"
                        elif chatTypeByte == 2:
                            chatType = "squad"
                        else:
                            chatType = "team"
                    else:
                        chatType = "unknown"
                                        
                    messages.append((playerName, message, chatType))
        except:
            continue

    return messages

def get_vehicles(data, numberOfPlayers):
    # Search for occurences of the following bytes
    lookup = b'\x90..\x01\x20\x01'
    # Find all occurences
    occurences = [m.start() for m in re.finditer(lookup, data, re.DOTALL)]
    # Player ID is 4 bytes before the occurence
    playerIndex = [int(data[i+PLAYER_ID_OFFSET]) for i in occurences]
    # For some reason, the player Index is offset by the number of players
    playerIndex = [i-(min(playerIndex)) for i in playerIndex]

    vehicleNameLengths = [int(data[i+VEHICLE_NAME_LENGTH]) for i in occurences]
    vehicleNames = [data[i+VEHICLE_NAME_START:i+VEHICLE_NAME_START+length].decode("utf-8") for i,length in zip(occurences, vehicleNameLengths)]
    
    # Create a dict of player IDs and vehicle names
    playerVehicles = dict()
    for index, vehicleName in zip(playerIndex, vehicleNames):
        if index not in playerVehicles:
            playerVehicles[index] = set([vehicleName])
        else:
            playerVehicles[index].add(vehicleName)
    return playerVehicles

def get_a_winning_player(data):
    # Look for 'hidden_win_streak' in the data
    winningPlayer = data.find(b'hidden_win_streak')
    # The winning player is 5 bytes before the string
    winningPlayer = data[winningPlayer-5]
    return winningPlayer
    
def parse_replay_data(data):
    # Find the start of the table
    startOfResultsTable = data.find(bytes(START_OF_TABLE))
    startOfResultsTable += len(START_OF_TABLE)
    
    resultsTable = data[startOfResultsTable:]
    
    # Find the end of the table
    endOfPlayersTable = resultsTable.find(bytes(END_OF_PLAYERS_SECTION))
    
    # Get the Players table
    playersTable = resultsTable[TABLE_HEADER_SIZE:endOfPlayersTable]

    players = get_players(playersTable)
    messages = get_messages(data, players)

    # Scores is from the players table to the START_OF_SCORES_SECTION
    scoresTable = resultsTable[endOfPlayersTable + len(END_OF_PLAYERS_SECTION):]
    startOfScoresTable = scoresTable.find(bytes(START_OF_SCORES_SECTION))
    scoresTable = scoresTable[startOfScoresTable + len(START_OF_SCORES_SECTION):]

    players = get_scores(scoresTable, players)
    
    # Get a winning player
    winningPlayer = get_a_winning_player(data)
    for ID, player in players.items():
        if player["index"] == winningPlayer:
            winningTeam = player["team"]
            break
    
    # Initialise vehicles and winning team
    for player in players.values():
        try:
            player["vehicles"] = []
            if player["team"] == winningTeam:
                player["win"] = True
            else:
                player["win"] = False
        except:
            # idk I forgot
            continue

    # Parse vehicles
    vehiclesList = get_vehicles(data, len(players))
    for index, vehicles in vehiclesList.items():
        for ID, player in players.items():
            if player["index"] == index:
                break
        if 'dummy_plane' not in vehicles:
            players[ID]["vehicles"] = vehicles
            # Get nation
            for vehicle in vehicles:
                nation = lookup_nation(vehicle)
                if nation is not None:
                    players[ID]["nation"] = nation
                    break
                else:
                    players[ID]["nation"] = None


    
    return players, messages

def convert_sets_to_lists(obj):
    if isinstance(obj, set):
        return list(obj)
    elif isinstance(obj, dict):
        return {k: convert_sets_to_lists(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_sets_to_lists(i) for i in obj]
    else:
        return obj

def main():

    file = sys.argv[1]
    
    # Expect a path to a folder, read all files in the folder and concat them
    if os.path.isdir(file):
        data = b''
        for f in os.listdir(file):
            # Only parse the files with an odd number
            # eg: 0007.wrpl
            if int(f.split(".")[0]) % 2 == 0:
                continue
            with open(os.path.join(file, f), "rb") as replay:
                data += replay.read()
    else:
        with open(file, "rb") as replay:
            data = replay.read()

    # Write the concatenated data to replay.bin
    # You don't need to do this, it's just for debugging and finding hex values etc easier
    with open('replay.bin', 'wb') as replay_file:
        replay_file.write(data)
    
    start = timeStart()
    players, messages = parse_replay_data(data)
    timeEnd(start)

    players_serializable = convert_sets_to_lists(players)

    print(json.dumps({"players": players_serializable}, indent=4))
    print(json.dumps({"messages": messages}, indent=4))
  

if __name__ == "__main__":
    main()