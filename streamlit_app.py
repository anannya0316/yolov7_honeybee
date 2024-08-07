import streamlit as st
import cv2
import subprocess
import sys
import shlex
import os
import shutil

def remove_numbers(input_string):
    return input_string.translate(str.maketrans('', '', '0123456789'))

def detect_labels(weights_path, confidence_threshold, image_path):
    # Validate the file paths
    if not os.path.exists(weights_path):
        raise FileNotFoundError(f"Weights file not found: {weights_path}")
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image file not found: {image_path}")

    # Run the YOLOv7 detection script
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

# Streamlit app
st.title("Object Detection with YOLOv7")

# Upload image
uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "jpeg", "png"])

# Parameters
weights_path = "best_v4.pt"
confidence_threshold = 0.1

if uploaded_file is not None:
    # Save the uploaded file
    image_path = os.path.join("yolov7/uploads", uploaded_file.name)
    if not os.path.exists("yolov7/uploads"):
        os.makedirs("yolov7/uploads")
    with open(image_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    # Detect labels
    try:
        labels = detect_labels(weights_path, confidence_threshold, image_path)
        st.image(image_path, caption='Uploaded Image.', use_column_width=True)
        st.write("Predicted Labels:")
        st.write(labels)
        
        # User options for classification
        classification = st.radio("Classify the predictions:", ("Good", "Bad"))
        
        if st.button("Submit Classification"):
            is_good = classification == "Good"
            save_image(image_path, is_good)
            st.success("Image classified and saved successfully!")

    except Exception as e:
        st.error(f"Error: {str(e)}")

# Run the app with `streamlit run streamlit_app.py`
