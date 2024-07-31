import streamlit as st
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os
import pickle

# Define the scope
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/cloud-platform']

# Authenticate and initialize API clients
def authenticate_google():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds

def execute_colab_notebook(notebook_url):
    creds = authenticate_google()
    drive_service = build('drive', 'v3', credentials=creds)
    # Extract the notebook ID from the URL
    notebook_id = notebook_url.split('/d/')[1].split('/')[0]
    
    # Create a copy of the notebook
    copy_title = "Executed Notebook"
    copied_file = drive_service.files().copy(fileId=notebook_id, body={"name": copy_title}).execute()

    # Get the link to the copied notebook
    copy_id = copied_file.get('id')
    colab_url = f"https://colab.research.google.com/drive/{copy_id}"

    # Note: There isn't a direct API to programmatically run the Colab notebook.
    # However, you can provide a link to the copied notebook for manual execution.
    return colab_url

st.title('Trigger Google Colab Notebook')

notebook_url = st.text_input('Enter Google Colab Notebook URL')
if st.button('Run Notebook'):
    if notebook_url:
        colab_url = execute_colab_notebook(notebook_url)
        st.write('Notebook execution initiated.')
        st.write(f'You can access the executed notebook [here]({colab_url}).')
    else:
        st.write('Please enter a valid Google Colab notebook URL.')
