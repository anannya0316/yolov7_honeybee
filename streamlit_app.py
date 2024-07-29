import streamlit as st
import io
import subprocess
import shlex
import os
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Google Drive API setup
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = r"C:\Users\anann\Documents\Lets Endorse\yolov7\yolov7-430911-60c202a365b7.json"

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build('drive', 'v3', credentials=credentials)

def download_file_from_drive(file_id, destination):
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(destination, mode='wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
        print(f"Download {int(status.progress() * 100)}%.")
    fh.close()

def download_google_drive_file(file_id, destination):
    URL = f"https://drive.google.com/uc?id={file_id}"
    session = requests.Session()
    response = session.get(URL, params={'confirm': 't'}, stream=True)
    with open(destination, "wb") as file:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                file.write(chunk)

def run_detection(weights_path, image_stream):
    # Save image temporarily
    image_path = 'temp_image.jpg'
    with open(image_path, 'wb') as f:
        f.write(image_stream.read())
    
    # Specify path to YOLOv7 directory
    yolov7_path = 'yolov7'
    if not os.path.exists(yolov7_path):
        os.makedirs(yolov7_path)
    
    # Download and extract YOLOv7 repository
    yolov7_zip_file_id = '1x6FKZDAOHJZFIDPCdmIEjgQxbMMUmJbE'  # Replace with your YOLOv7 zip file ID
    zip_file_path = 'yolov7.zip'
    download_google_drive_file(yolov7_zip_file_id, zip_file_path)
    
    # Check if the ZIP file exists and its size
    if not os.path.exists(zip_file_path) or os.path.getsize(zip_file_path) == 0:
        raise RuntimeError(f"Failed to download YOLOv7 zip file or file is empty.")

    # Extract the ZIP file
    try:
        subprocess.run(f"unzip {zip_file_path} -d {yolov7_path}", shell=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error extracting YOLOv7 repository: {e}")

    command = f"python {yolov7_path}/detect1.py --weights {weights_path} --conf 0.1 --source {image_path}"
    process = subprocess.Popen(shlex.split(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    
    if process.returncode != 0:
        raise RuntimeError(f"Command failed with error: {error.decode('utf-8')}")
    
    predictions = output.decode("utf-8").split('\n')
    
    result_line_index = None
    for i, line in enumerate(predictions):
        if "The image with the result is saved in:" in line:
            result_line_index = i - 1
            break
    
    if result_line_index is not None and 0 <= result_line_index < len(predictions):
        result_line = predictions[result_line_index].strip()
        result_line = result_line.split(', Done.')[0]
        labels = [label.strip() for label in result_line.split(',')]
        return labels
    else:
        return []

# Streamlit app
st.title("Object Detection with YOLOv7")

# Download weights file from Google Drive
weights_file_id = '1UzvQeWrRRY__czxu9p3dNSG_4Ksf-NsA'
weights_path = 'temp_weights.pt'
download_file_from_drive(weights_file_id, weights_path)

# YOLOv7 repo zip file ID
yolov7_zip_file_id = '1x6FKZDAOHJZFIDPCdmIEjgQxbMMUmJbE'  # Replace with your YOLOv7 zip file ID

# Parameters
confidence_threshold = 0.1

uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    try:
        # Detect labels
        labels = run_detection(weights_path, uploaded_file)
        st.image(uploaded_file, caption='Uploaded Image.', use_column_width=True)
        st.write("Predicted Labels:")
        st.write(labels)

        classification = st.radio("Classify the predictions:", ("Good", "Bad"))
        
        if st.button("Submit Classification"):
            is_good = classification == "Good"
            st.success("Image classified successfully!")

    except Exception as e:
        st.error(f"Error: {str(e)}")
