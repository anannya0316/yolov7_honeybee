import streamlit as st
import requests
import os
import time

# Function to trigger the Kaggle notebook
def trigger_kaggle_notebook(api_key, version_number):
    # Read the Kaggle notebook template
    with open("kaggle_notebook.py", "r") as file:
        kaggle_notebook_code = file.read()

    # Replace placeholders with actual values
    kaggle_notebook_code = kaggle_notebook_code.replace("VERSION_NUMBER_PLACEHOLDER", version_number)

    # Save the modified notebook code
    with open("kaggle_notebook_temp.py", "w") as file:
        file.write(kaggle_notebook_code)

    # Push the modified notebook to Kaggle
    response = requests.post(
        url='https://www.kaggle.com/api/v1/kernels/push',
        headers={
            'Authorization': f'Bearer {api_key}'
        },
        files={
            'file': ('kaggle_notebook_temp.py', open('kaggle_notebook_temp.py', 'rb'), 'text/plain')
        },
        data={
            'kernel_slug': 'yolov7_training',  # Change this to a unique identifier for your kernel
            'public': 'false',
            'enable_gpu': 'true'  # Request GPU usage
        }
    )
    if response.status_code != 200:
        st.error(f"Failed to push to Kaggle: {response.json()}")
    return response.json()

# Function to check the status of the Kaggle notebook
def check_notebook_status(kernel_slug, api_key):
    response = requests.get(
        f"https://www.kaggle.com/api/v1/kernels/status/{kernel_slug}",
        headers={"Authorization": f"Bearer {api_key}"}
    )
    return response.json()

# Function to download the best.pt weights
def download_weights(file_url, save_path):
    response = requests.get(file_url, stream=True)
    with open(save_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    st.success("Downloaded best.pt weights.")

st.title("YOLOv7 Training Interface")

# Roboflow API credentials
rf_api_key = "YvqMXpoGrLg1JSJ7URgW"
workspace_name = "anannya-c7n8q"
project_name = "bee-classification-dd6lv"

# Ask user for the version number
version_number = st.text_input("Version Number")

if version_number:
    if st.button("Start Training"):
        try:
            # Access Kaggle API details from Streamlit secrets
            kaggle_username = st.secrets["kaggle"]["username"]
            kaggle_api_key = st.secrets["kaggle"]["key"]

            # Trigger the Kaggle notebook
            response = trigger_kaggle_notebook(kaggle_api_key, version_number)
            st.write(response)
            notebook_url = f"https://www.kaggle.com/{kaggle_username}/kernels/edit/{response['id']}"
            st.write(f"Notebook URL: {notebook_url}")

            st.success("Training has started on Kaggle! Check your Kaggle account for progress.")
            
            # Poll the Kaggle API to check the status
            kernel_slug = 'yolov7_training'  # Use the same kernel_slug as above
            while True:
                status = check_notebook_status(kernel_slug, kaggle_api_key)
                st.write(f"Notebook Status: {status['status']}")
                if status['status'] == 'complete':
                    st.success("Training is complete!")
                    break
                elif status['status'] == 'error':
                    st.error("An error occurred during training.")
                    break
                time.sleep(60)  # Wait for 1 minute before checking again

            # Download the weights file
            file_url = f"https://www.kaggle.com/{kaggle_username}/kernels/output/{kernel_slug}/yolov7_weights.zip"
            save_path = os.path.join(os.path.expanduser('~/Downloads'), 'yolov7_weights.zip')
            download_weights(file_url, save_path)

            st.success("Training and download complete! Check your Downloads folder for the weights.")
        
        except KeyError as e:
            st.error(f"Missing secret: {e}. Please check your Streamlit secrets configuration.")
        except Exception as e:
            st.error(f"An error occurred: {e}")
