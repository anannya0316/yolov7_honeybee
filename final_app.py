import streamlit as st
import subprocess
import shlex
import os
import shutil
from pymongo import MongoClient
import boto3
from io import BytesIO
from PIL import Image
from datetime import datetime

# Local configuration for S3 and MongoDB
IMAGE_S3_BUCKET_NAME = os.getenv("IMAGE_S3_BUCKET_NAME")
IMAGE_S3_ACCESS_KEY = os.getenv("IMAGE_S3_ACCESS_KEY")
IMAGE_S3_SECRET_KEY = os.getenv("IMAGE_S3_SECRET_KEY")
IMAGE_S3_REGION_NAME = os.getenv("IMAGE_S3_REGION_NAME")
MONGODB_URI = os.getenv("MONGODB_URI")

# MongoDB Client
client = MongoClient(MONGODB_URI)
db = client['humble_bee']
detection_collection = db['beehive_detection_records']
classification_collection = db['classification_of_results']

# S3 Client
s3_client = boto3.client(
    's3',
    aws_access_key_id=IMAGE_S3_ACCESS_KEY,
    aws_secret_access_key=IMAGE_S3_SECRET_KEY,
    region_name=IMAGE_S3_REGION_NAME
)

# Authentication
def authenticate(username, password):
    """Authenticate the user with predefined credentials."""
    return username == "beekind" and password == "beekind"

# Utility Functions
def remove_numbers(input_string):
    return input_string.translate(str.maketrans('', '', '0123456789'))

def detect_labels(weights_path, confidence_threshold, image_path):
    # Validate the file paths
    if not os.path.exists(weights_path):
        raise FileNotFoundError(f"Weights file not found: {weights_path}")
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image file not found: {image_path}")

    command = f"python yolov7/detect1.py --weights \"{weights_path}\" --conf {confidence_threshold} --source \"{image_path}\""
    process = subprocess.Popen(shlex.split(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"Command failed with error: {error.decode('utf-8')}")

    predictions = output.decode("utf-8").split('\n')

    # Find the line before "The image with the result is saved in..."
    result_line_index = None
    for i, line in enumerate(predictions):
        if "The image with the result is saved in:" in line:
            result_line_index = i - 1
            break

    if result_line_index is not None and 0 <= result_line_index < len(predictions):
        result_line = predictions[result_line_index].strip()
        # Remove "Done. (14.5ms) Inference, (595.8ms) NMS" part
        result_line = result_line.split(', Done.')[0]
        # Remove numbers and return labels
        labels = [label.strip() for label in result_line.split(',')]
        labels = [remove_numbers(label).strip() for label in labels]
        return labels
    else:
        return []

def save_image(image_path, is_good):
    # Define directories
    download_path = os.path.expanduser('~/Downloads')
    correct_folder = os.path.join(download_path, 'correct')
    incorrect_folder = os.path.join(download_path, 'incorrect')

    # Create folders if they do not exist
    if not os.path.exists(correct_folder):
        os.makedirs(correct_folder)
    if not os.path.exists(incorrect_folder):
        os.makedirs(incorrect_folder)

    # Move image to the correct folder
    if is_good:
        shutil.move(image_path, os.path.join(correct_folder, os.path.basename(image_path)))
    else:
        shutil.move(image_path, os.path.join(incorrect_folder, os.path.basename(image_path)))

def list_images_from_s3(bucket_name):
    """List image files from the specified S3 bucket, excluding certain prefixes."""
    response = s3_client.list_objects_v2(Bucket=bucket_name)
    images = []
    
    # Collect all image files
    for obj in response.get('Contents', []):
        key = obj['Key']
        # Filter image files, ignoring those with the prefix "qu13edjkbs"
        if key.endswith(('.png', '.jpg', '.jpeg')) and not key.startswith('qu13edjkbs'):
            images.append(key)
    
    return images

def fetch_bad_images_from_mongo():
    """Fetch image keys of bad images from MongoDB."""
    # Query MongoDB for images classified as "Bad"
    bad_images = classification_collection.find({"classification": "Bad"})
    return [image['s3_filename'] for image in bad_images]

def fetch_image_from_s3(bucket_name, key):
    """Fetch an image from S3 by its key."""
    response = s3_client.get_object(Bucket=bucket_name, Key=key)
    return response['Body'].read()

def download_images_to_folders(image_keys, base_download_path, max_images_per_folder=100):
    """Download images to local folders, limiting to max_images_per_folder per folder."""
    os.makedirs(base_download_path, exist_ok=True)
    
    # Create a set to keep track of all existing images to avoid duplicates
    existing_images = set()
    
    # Initialize folder counter and image counter
    folder_counter = 1
    image_counter = 0
    current_folder = os.path.join(base_download_path, f"images_batch_{folder_counter}")
    os.makedirs(current_folder, exist_ok=True)
    
    for key in image_keys:
        try:
            filename = os.path.basename(key)
            
            # Check for duplicate images using a set
            if filename in existing_images:
                st.info(f"Duplicate image detected: {filename}. Skipping download.")
                continue
            
            local_filename = os.path.join(current_folder, filename)

            # Fetch the image from S3
            image_data = fetch_image_from_s3(IMAGE_S3_BUCKET_NAME, key)
            img = Image.open(BytesIO(image_data))
            img.save(local_filename)
            
            # Update existing images set and counters
            existing_images.add(filename)
            image_counter += 1
            
            # Check if the current folder has reached the maximum number of images
            if image_counter >= max_images_per_folder:
                folder_counter += 1
                current_folder = os.path.join(base_download_path, f"images_batch_{folder_counter}")
                os.makedirs(current_folder, exist_ok=True)
                image_counter = 0  # Reset counter for the new folder

        except Exception as e:
            st.error(f"Failed to download image {key}: {str(e)}")

    st.success(f"Downloads completed. Total folders created: {folder_counter}")

def fetch_details_from_mongo(s3_filename):
    """Fetch image details from MongoDB."""
    # Find the document in MongoDB that matches the s3_filename
    return detection_collection.find_one({"s3_filename": s3_filename})

def extract_dates_from_keys(keys):
    """Extract unique dates from S3 image keys."""
    dates = set()
    for key in keys:
        # Assuming the filename format is "userid/images/YYYYMMDDHHMMSS.png"
        parts = key.split('/')
        if len(parts) > 1:
            date_str = parts[-1][:8]  # Extract YYYYMMDD from the filename
            try:
                date_obj = datetime.strptime(date_str, "%Y%m%d")
                dates.add(date_obj)
            except ValueError:
                pass  # Skip any filenames that don't match the date format
    return sorted(dates)

def get_existing_classification(s3_filename):
    """Check if the image is already classified and return its classification."""
    return classification_collection.find_one({"s3_filename": s3_filename})

def update_classification_in_mongo(s3_filename, new_classification):
    """Update the classification in MongoDB, removing the previous one."""
    classification_collection.delete_many({"s3_filename": s3_filename})
    # Insert new classification
    classification_collection.insert_one(new_classification)

def save_classification_to_mongo(s3_filename, classification, details):
    """Save the classification to MongoDB."""
    # Prepare the data to be inserted
    metadata = {
        "s3_filename": s3_filename,
        "classification": classification,
        "user_id": details.get('userid', 'N/A'),
        "uploaded_at": details.get('uploaded_at', 'N/A'),
        "timestamp": details.get('timestamp', 'N/A'),
        "language": details.get('language', 'N/A'),
        "predictions": details.get('detection_results', [])
    }
    # Remove old classifications and insert the new one
    classification_collection.delete_many({"s3_filename": s3_filename})
    classification_collection.insert_one(metadata)

def fetch_classification_counts():
    """Fetch classification counts from MongoDB."""
    good_count = classification_collection.count_documents({"classification": "Good"})
    bad_count = classification_collection.count_documents({"classification": "Bad"})
    return good_count, bad_count

# Streamlit App
st.set_page_config(page_title="Beehive Image Detection", page_icon="🐝", layout="wide")

st.title("🐝 Beehive Image Detection and Management")

# Sidebar for authentication
st.sidebar.header("Authentication")
username = st.sidebar.text_input("Username")
password = st.sidebar.text_input("Password", type="password")

if authenticate(username, password):
    st.sidebar.success("Authenticated")
    
    # Display count of Good and Bad images
    good_count, bad_count = fetch_classification_counts()
    st.sidebar.write(f"Good Images: {good_count}")
    st.sidebar.write(f"Bad Images: {bad_count}")

    # Download images section
    st.header("Download Images")
    if st.button("Download Images from S3"):
        try:
            # List images from S3 and fetch bad images from MongoDB
            all_image_keys = list_images_from_s3(IMAGE_S3_BUCKET_NAME)
            bad_image_keys = fetch_bad_images_from_mongo()
            
            # Filter to only include bad images
            image_keys_to_download = [key for key in all_image_keys if key in bad_image_keys]
            base_download_path = os.path.expanduser('~/Downloads/bad_images')
            download_images_to_folders(image_keys_to_download, base_download_path)

        except Exception as e:
            st.error(f"An error occurred: {str(e)}")
else:
    st.warning("Please enter valid credentials.")

st.sidebar.text("Built with Streamlit and AWS S3")

