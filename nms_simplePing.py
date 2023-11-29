import pymongo
from datetime import datetime
import subprocess

def check_ping(ip_address, count=4):
    try:
        # Use subprocess to run the ping command
        result = subprocess.run(['ping', '-c', str(count), ip_address], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)

        if result.returncode == 0:
            return {
                "status": "success",
                "response": result.stdout.strip(),
            }
        else:
            return {
                "status": "failure",
                "error": result.stderr.strip(),
            }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "error": f"Ping to {ip_address} timed out.",
        }

def process_camera(camera, collection):
    camera_name = camera["camera_name"]
    ip_address = camera["ip_address"]
    rtsp_link = camera["rtsp_link"]

    timestamp = datetime.utcnow()
    ping_result = check_ping(ip_address)
    
    # Store ping result in MongoDB
    collection.insert_one({
        "camera_name": camera_name,
        "ip_address": ip_address,
        "rtsp_link": rtsp_link,
        "timestamp": timestamp,
        "ping_result": ping_result,
    })

    print(f"{camera_name}: Ping result stored in MongoDB at {timestamp}")

def main():
    # MongoDB connection parameters
    MONGODB_URI = "your_mongodb_uri"
    DB_NAME = "your_database_name"
    COLLECTION_NAME = "ping_results"

    # Connect to MongoDB
    client = pymongo.MongoClient(MONGODB_URI)
    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]

    # List of cameras as JSON objects
    cameras = [
        {"camera_name": "Camera1", "ip_address": "192.1.48.50", "rtsp_link": "rtsp://camera1"},
        {"camera_name": "Camera2", "ip_address": "192.1.48.12", "rtsp_link": "rtsp://camera2"},
        # Add more cameras as needed
    ]

    for camera in cameras:
        process_camera(camera, collection)

    # Close the MongoDB connection
    client.close()

if __name__ == "__main__":
    main()
