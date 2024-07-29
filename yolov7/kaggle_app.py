import streamlit as st
import subprocess
import shlex
import os

def remove_numbers(input_string):
    return input_string.translate(str.maketrans('', '', '0123456789'))

def detect_labels(weights_path, confidence_threshold, image_path):
    # Validate the file paths
    if not os.path.exists(weights_path):
        raise FileNotFoundError(f"Weights file not found: {weights_path}")
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image file not found: {image_path}")

    command = f"python detect1.py --weights \"{weights_path}\" --conf {confidence_threshold} --source \"{image_path}\""
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

# Streamlit app
st.title("Object Detection with YOLOv7")

# Upload image
uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "jpeg", "png"])

# Parameters
weights_path = "best.pt"
confidence_threshold = 0.1

if uploaded_file is not None:
    # Save the uploaded file
    image_path = os.path.join("uploads", uploaded_file.name)
    with open(image_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    # Detect labels
    try:
        labels = detect_labels(weights_path, confidence_threshold, image_path)
        st.image(image_path, caption='Uploaded Image.', use_column_width=True)
        st.write("Predicted Labels:")
        st.write(labels)
    except Exception as e:
        st.error(f"Error: {str(e)}")
