# Install necessary libraries
!pip install roboflow
!pip install torch torchvision torchaudio

# Clone the YOLOv7 repository
!git clone https://github.com/WongKinYiu/yolov7.git
%cd yolov7
!pip install -r requirements.txt

# Import necessary libraries
import os
import zipfile
import torch

# Set the necessary variables (these will be passed from the Streamlit app)
YOUR_ROBOFLOW_API_KEY = "YvqMXpoGrLg1JSJ7URgW"
WORKSPACE_NAME = "anannya-c7n8q"
PROJECT_NAME = "bee-classification-dd6lv"
VERSION_NUMBER = "VERSION_NUMBER_PLACEHOLDER"

# Authenticate with Roboflow
from roboflow import Roboflow
rf = Roboflow(api_key=YOUR_ROBOFLOW_API_KEY)
project = rf.workspace(WORKSPACE_NAME).project(PROJECT_NAME)
dataset = project.version(VERSION_NUMBER).download("yolov7")

# Train YOLOv7
!python train.py --data {dataset.location}/data.yaml --cfg yolov7.yaml --weights 'yolov7.pt' --name yolov7_custom --epochs 100

# Save weights to output directory
output_directory = '/kaggle/working/yolov7/runs/train/yolov7_custom/weights'
weights_path = os.path.join(output_directory, 'best.pt')
print(f"Trained weights saved to: {weights_path}")

# Optionally, compress the weights file
with zipfile.ZipFile('/kaggle/working/yolov7_weights.zip', 'w') as zf:
    zf.write(weights_path, os.path.basename(weights_path))

print("Weights have been zipped and are ready for upload.")

# Upload the weights to GitHub repository
# Replace the following with your GitHub repository details
repo_url = "https://github.com/anannya0316/yolov7_honeybee.git"
repo_dir = "/kaggle/working/yolov7_honeybee"
branch_name = "main"

# Clone the repository
!git clone {repo_url} {repo_dir}

# Copy the weights file to the repository directory
!cp /kaggle/working/yolov7_weights.zip {repo_dir}

# Change directory to the repository directory
os.chdir(repo_dir)

# Add, commit, and push the weights file to GitHub
!git config --global user.email "anannya0316@gmail.com"
!git config --global user.name "anannya0316"
!git add yolov7_weights.zip
!git commit -m "Add trained YOLOv7 weights"
!git push origin {branch_name}

print("Weights have been uploaded to GitHub.")
