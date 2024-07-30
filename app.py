import streamlit as st
import requests
import os

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
            'kernel_slug': 'YOUR_KERNEL_SLUG',
            'public': 'false',
            'enable_gpu': 'true'  # Request GPU usage
        }
    )
    return response.json()

st.title("YOLOv7 Training Interface")

# Roboflow API credentials
rf_api_key = "YvqMXpoGrLg1JSJ7URgW"
workspace_name = "anannya-c7n8q"
project_name = "merged-images-5t6hv"

# Ask user for the version number
version_number = st.text_input("Version Number")

if version_number:
    if st.button("Start Training"):
        # Access Kaggle API details from Streamlit secrets
        kaggle_username = st.secrets["kaggle"]["username"]
        kaggle_api_key = st.secrets["kaggle"]["key"]

        # Trigger the Kaggle notebook
        response = trigger_kaggle_notebook(kaggle_api_key, version_number)
        st.write(response)

        st.success("Training has started on Kaggle! Check your Kaggle account for progress.")
