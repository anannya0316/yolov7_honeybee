import streamlit as st
from pymongo import MongoClient
import boto3
from io import BytesIO
from PIL import Image
from datetime import datetime
import os

# Local configuration for S3 and MongoDB
IMAGE_S3_BUCKET_NAME = st.secrets["aws"]["bucket_name"]
IMAGE_S3_ACCESS_KEY = st.secrets["aws"]["access_key"]
IMAGE_S3_SECRET_KEY = st.secrets["aws"]["secret_key"]
IMAGE_S3_REGION_NAME = st.secrets["aws"]["region_name"]

MONGODB_URI = st.secrets["mongodb"]["uri"]

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
    return [image['s3_filename'] for image in bad_images if 's3_filename' in image]

def fetch_image_from_s3(bucket_name, key):
    """Fetch an image from S3 by its key."""
    response = s3_client.get_object(Bucket=bucket_name, Key=key)
    return response['Body'].read()

from pathlib import Path
import os

def get_downloads_folder():
    """Get the path to the user's Downloads folder."""
    home = Path.home()
    downloads = home / 'Downloads'
    return downloads

def download_images_to_folders(image_keys, max_images_per_folder=100):
    """Download images to local folders, limiting to max_images_per_folder per folder."""
    base_download_path = get_downloads_folder() / 'wrong_classification'
    base_download_path.mkdir(parents=True, exist_ok=True)
    
    # Create a set to keep track of all existing images to avoid duplicates
    existing_images = set()
    
    # Initialize folder counter and image counter
    folder_counter = 1
    image_counter = 0
    current_folder = base_download_path / f"images_batch_{folder_counter}"
    current_folder.mkdir(parents=True, exist_ok=True)
    
    for key in image_keys:
        try:
            filename = os.path.basename(key)
            
            # Check for duplicate images using a set
            if filename in existing_images:
                st.info(f"Duplicate image detected: {filename}. Skipping download.")
                continue
            
            local_filename = current_folder / filename

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
                current_folder = base_download_path / f"images_batch_{folder_counter}"
                current_folder.mkdir(parents=True, exist_ok=True)
                image_counter = 0  # Reset counter for the new folder

        except Exception as e:
            st.error(f"Failed to download image {key}: {str(e)}")

    st.success(f"Downloads completed. Total folders created: {folder_counter}")
    st.write(f"Files saved to: {base_download_path}")

    # Debug: list files in the download directory
    st.write("Files in download directory:")
    for root, dirs, files in os.walk(base_download_path):
        for file in files:
            st.write(os.path.join(root, file))



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
st.title("Beehive Image Classification and Management")

# Fetch image keys from S3 bucket
image_keys = list_images_from_s3(IMAGE_S3_BUCKET_NAME)

# Extract available dates from image keys
available_dates = extract_dates_from_keys(image_keys)

if not available_dates:
    st.warning("No images found in the S3 bucket.")
else:
    # Dropdown for selecting a date
    date_selected = st.selectbox("Select Date", available_dates, format_func=lambda x: x.strftime('%B %d, %Y'))

    # Convert the selected date to string format YYYYMMDD
    date_str = date_selected.strftime("%Y%m%d")

    # Filter image keys based on the selected date
    filtered_keys = [key for key in image_keys if date_str in key]

    # Debug: Display the number of images found for the selected date
    st.write(f"Number of images found for {date_selected.strftime('%B %d, %Y')}: {len(filtered_keys)}")

    if not filtered_keys:
        st.warning(f"No images found for the selected date: {date_selected.strftime('%B %d, %Y')}.")
    else:
        # Initialize session state for image index
        if 'image_index' not in st.session_state:
            st.session_state.image_index = 0

        # Define navigation buttons with disabled state logic
        col1, col2, col3 = st.columns([1, 1, 1])

        with col1:
            st.button("Previous", 
                      disabled=(st.session_state.image_index == 0),
                      on_click=lambda: st.session_state.update(image_index=st.session_state.image_index - 1)
            )

        with col3:
            st.button("Next", 
                      disabled=(st.session_state.image_index == len(filtered_keys) - 1),
                      on_click=lambda: st.session_state.update(image_index=st.session_state.image_index + 1)
            )

        # Fetch the selected image
        if 0 <= st.session_state.image_index < len(filtered_keys):
            key = filtered_keys[st.session_state.image_index]
            image_data = fetch_image_from_s3(IMAGE_S3_BUCKET_NAME, key)
            img = Image.open(BytesIO(image_data))
            st.image(img, caption=f"**Image:** {key}", use_column_width=True)

            # Fetch and display detection results from MongoDB
            details = fetch_details_from_mongo(key)
            if details:
                st.write("### Detection Results:")
                predictions = details.get('detection_results', [])
                if predictions:
                    for prediction in predictions:
                        label = prediction.get('label', 'Unknown')
                        percentage = prediction.get('percentage', 0)
                        st.write(f"- **{label}**: {percentage}%")
                else:
                    st.write("No detection results available")

                # Check for existing classification
                existing_classification = get_existing_classification(key)

                if existing_classification:
                    st.markdown(f"<large>**Current Classification:** {existing_classification['classification']}</large>", unsafe_allow_html=True)
                    st.markdown(f"<medium>Do you want to change the classification for {key}?</medium>",unsafe_allow_html=True)
                    change_classification = st.radio(
                        "Select an option",
                        ('Keep Existing', 'Change'),
                        index=0
                    )
                    if change_classification == 'Change':
                        new_classification = st.radio(
                            f"New Classification for {key}",
                            ('Good', 'Bad'),
                            index=0
                        )
                        if st.button(f"Update Classification for {key}", key=f"update_{key}"):
                            # Update classification
                            update_classification_in_mongo(key, {
                                "s3_filename": key,
                                "classification": new_classification,
                                "user_id": details.get('userid', 'N/A'),
                                "uploaded_at": details.get('uploaded_at', 'N/A'),
                                "timestamp": details.get('timestamp', 'N/A'),
                                "language": details.get('language', 'N/A'),
                                "predictions": details.get('detection_results', [])
                            })
                            st.success(f"Classification for {key} updated successfully to {new_classification}.")

                else:
                    # Classification Section
                    st.write("### Classify the Image")
                    classification = st.radio(f"Classification for {key}", ('Good', 'Bad'), index=0)

                    # Button to save classification
                    if st.button(f"Save Classification for {key}", key=f"save_{key}"):
                        save_classification_to_mongo(key, classification, details)
                        st.success(f"Classification for {key} saved successfully as {classification}.")
            else:
                st.write("No detection results available.")

        # Only show classification and download buttons once
        st.write("---")  # Add a separator for clarity

        # Horizontal Layout for buttons
        col1, col2 = st.columns(2)

        with col1:
            if st.button("Show Total Classifications"):
                good_count, bad_count = fetch_classification_counts()
                st.write(f"Total Good Classifications: {good_count}")
                st.write(f"Total Bad Classifications: {bad_count}")

        with col2:
            if st.button("Download Bad Images to Local Folders"):
                # Fetch all bad image keys from MongoDB
                bad_image_keys = fetch_bad_images_from_mongo()
                if not bad_image_keys:
                    st.warning("No bad images found in the MongoDB collection.")
                else:
                    # Define the base download path (your local Downloads folder)
                    base_download_path = os.path.expanduser("~/Downloads/wrong_classification")

                    # Download images to local folders, ensuring no duplicates
                    download_images_to_folders(bad_image_keys, base_download_path, max_images_per_folder=100)
