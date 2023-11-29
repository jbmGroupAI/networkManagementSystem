import subprocess
import cv2
import multiprocessing
import time
import pymongo
import json
import logging
import csv
import math

# Constants for alert levels
ALERT_LEVEL_1_THRESHOLD = 10  # seconds
ALERT_LEVEL_2_THRESHOLD = 60  # seconds
ALERT_LEVEL_3_THRESHOLD = 300  # seconds

logging.basicConfig(level=logging.INFO)

UNAUTHORIZED_CAMERAS_CSV_FILE = "unauthorized_cameras.csv"

def check_ping(ip_address, count=4):
    try:
        result = subprocess.run(['ping', '-c', str(count), ip_address], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)

        if result.returncode == 0:
            rtt_line = [line for line in result.stdout.split('\n') if 'time=' in line]
            if rtt_line:
                rtt = float(rtt_line[0].split('time=')[-1].split(' ')[0])
            else:
                rtt = None

            return {
                "status": "success",
                "response": result.stdout.strip(),
                "rtt": rtt,
            }
        else:
            return {
                "status": "failure",
                "error": result.stderr.strip(),
                "rtt": None,
            }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "error": f"Ping to {ip_address} timed out.",
            "rtt": None,
        }

def form_rtsp_link(username, password, make, ip_address):
    make_lower = make.lower()

    if make_lower == "hikvision":
        return f"rtsp://{username}:{password}@{ip_address}/Streaming/Channels/101"
    elif make_lower == "wbox":
        return f"rtsp://{username}:{password}@{ip_address}:554/snl/live/1/1"  # Adjust the Stream ID if needed
    elif make_lower == "cp plus":
        return f"rtsp://{username}:{password}@{ip_address}"
    else:
        return None

def check_rtsp(camera, interval_seconds, db_collection):
    camera_name = camera.get("Camera ID", "Unknown Camera")
    ip_address = camera.get("Camera IP")
    username = camera.get("Camera Username")
    password = camera.get("Camera Password")
    make = camera.get("Camera Make", "").lower()

    logging.info(f"Checking camera {camera_name}...")  # Log statement for checking the camera

    rtsp_link = form_rtsp_link(username, password, make, ip_address)
    if rtsp_link is None:
        logging.error(f"RTSP link not formed for {camera_name}")
        return

    downtime_duration = 0
    alert_type = "NoAlert"

    cap = cv2.VideoCapture(rtsp_link)

    # Check if the username and password are correct
    authorized = False
    try:
        if cap.isOpened():
            authorized = True
    except Exception as e:
        logging.error(f"Error checking RTSP link for {camera_name}: {str(e)}")

    while True:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        ping_result = check_ping(ip_address)

        status = "inactive"

        rtt = ping_result.get("rtt", None)
        logging.info(f"{camera_name}: Ping check result RTT - {rtt}")

        if authorized and rtt is not None:
            downtime_duration = 0
            alert_type = "NoAlert"

            # Log and insert into the database for cameras working fine
            logging.info(f"{camera_name}: Camera is active at {timestamp}, RTT: {rtt} ms")
            db_collection.insert_one({
                "camera_name": camera_name,
                "timestamp": timestamp,
                "ping_result": ping_result,
                "rtsp_status": "active",
                "downtime_duration": downtime_duration,
                "alert_type": alert_type,
                "camera_details": camera  # Store all camera details in the camera_details field
            })
        else:
            if not authorized:
                # Log unauthorized alert reason
                alert_type = "Unauthorized"
                logging.warning(f"{camera_name}: Unauthorized access to the camera")

                # Save unauthorized camera details to CSV file
                save_unauthorized_camera_to_csv(camera, timestamp)

            else:
                downtime_duration += interval_seconds
                if downtime_duration >= ALERT_LEVEL_1_THRESHOLD and downtime_duration < ALERT_LEVEL_2_THRESHOLD:
                    alert_type = "AlertLevel1"
                    logging.warning(f"{camera_name}: Alert Level 1 - Downtime Duration: {downtime_duration} seconds")
                elif downtime_duration >= ALERT_LEVEL_2_THRESHOLD and downtime_duration < ALERT_LEVEL_3_THRESHOLD:
                    alert_type = "AlertLevel2"
                    logging.error(f"{camera_name}: Alert Level 2 - Downtime Duration: {downtime_duration} seconds")
                elif downtime_duration >= ALERT_LEVEL_3_THRESHOLD:
                    alert_type = "AlertLevel3"
                    logging.error(f"{camera_name}: Alert Level 3 - Downtime Duration: {downtime_duration} seconds")

        time.sleep(interval_seconds)

    cap.release()

def save_unauthorized_camera_to_csv(camera, timestamp):
    unauthorized_cameras_data = {
        "Timestamp": timestamp,
        "Camera Name": camera.get("Camera ID", "Unknown Camera"),
        "Camera IP": camera.get("Camera IP"),
        "Camera Username": camera.get("Camera Username"),
        "Camera Password": camera.get("Camera Password"),
    }

    with open(UNAUTHORIZED_CAMERAS_CSV_FILE, mode='a', newline='') as csvfile:
        fieldnames = ["Timestamp", "Camera Name", "Camera IP", "Camera Username", "Camera Password"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        if csvfile.tell() == 0:  # If the file is empty, write the header
            writer.writeheader()

        writer.writerow(unauthorized_cameras_data)

def check_rtsp_batch(cameras, interval_seconds, db_collection):
    for camera in cameras:
        try:
            logging.info(f"Processing camera {camera.get('Camera ID', 'Unknown Camera')}...")
            check_rtsp(camera, interval_seconds, db_collection)
            logging.info(f"Processing for camera {camera.get('Camera ID', 'Unknown Camera')} complete.")
        except Exception as e:
            logging.error(f"Error processing camera {camera.get('Camera ID', 'Unknown Camera')}: {str(e)}")

def read_camera_details_from_json(file_path):
    try:
        with open(file_path, 'r') as file:
            data = json.load(file)

        if isinstance(data, list):
            return data
        else:
            print("[ERROR] JSON format is invalid. Expecting an array of objects.")
            return []
    except json.JSONDecodeError as e:
        print(f"[ERROR] Error decoding JSON: {str(e)}")
        return []
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred: {str(e)}")
        return []

def main():
    MONGODB_URI = "mongodb://localhost:27017/"
    DB_NAME = "nmsDB"
    COLLECTION_NAME = "nmsRaw"

    client = pymongo.MongoClient(MONGODB_URI)
    db = client[DB_NAME]
    db_collection = db[COLLECTION_NAME]

    interval_seconds = 10

    json_file_path = "/home/sahil/gitProgs/jbmProjects/NMS/cameraList.json"

    iteration = 0

    while True:
        cameras = read_camera_details_from_json(json_file_path)

        num_processes = 4
        chunk_size = math.ceil(len(cameras) / num_processes)

        processes = []

        for i in range(num_processes):
            process_cameras_chunk = cameras[i * chunk_size:(i + 1) * chunk_size]
            process = multiprocessing.Process(target=check_rtsp_batch, args=(process_cameras_chunk, interval_seconds, db_collection))
            processes.append(process)
            process.start()

        # Wait for all processes to finish
        for process in processes:
            process.join()

        logging.info(f"Iteration {iteration} complete. Waiting for the next iteration.")
        iteration += 1

        # Add a delay before checking cameras again
        time.sleep(interval_seconds)

if __name__ == "__main__":
    main()
