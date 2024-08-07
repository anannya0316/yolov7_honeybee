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

def fetch_image_from_s3(bucket_name, key):
    """Fetch an image from S3 by its key."""
    response = s3_client.get_object(Bucket=bucket_name, Key=key)
    return response['Body'].read()

def extract_dates_from_keys(keys):
    """Extract unique dates from S3 image keys."""
    dates = set()
    for key in keys:
        # Assuming the filename format is "userid/images/YYYYMMDDHHMMSS.png"
        parts = key.split('/')
        if len(parts) > 1:
            # Change: Use the last part of the key for consistent parsing
            filename = parts[-1]
            date_str = filename[:8]  # Extract YYYYMMDD from the filename
            try:
                date_obj = datetime.strptime(date_str, "%Y%m%d")
                dates.add(date_obj)
            except ValueError:
                pass  # Skip any filenames that don't match the date format
    return sorted(dates)

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
            details = detection_collection.find_one({"s3_filename": key})
            if details and details.get('detection_results'):
                st.write("### Detection Results:")
                predictions = details.get('detection_results', [])
                for prediction in predictions:
                    label = prediction.get('label', 'Unknown')
                    percentage = prediction.get('percentage', 0)
                    st.write(f"- **{label}**: {percentage}%")
            else:
                st.write("No detection results available.")
