
import io
import os
from typing import Union
import numpy as np
import librosa
import soundfile as sf
from pydub import AudioSegment

MAX_INT16 = 32768
SUPPORTED_AUDIO = ["mp3","flac","wav"] # ogg breaks soundfile
AUTOTUNE_NOTES = np.array([
    65.41, 69.30, 73.42, 77.78, 82.41, 87.31,
    92.50, 98.00, 103.83, 110.00, 116.54, 123.47,
    130.81, 138.59, 146.83, 155.56, 164.81, 174.61,
    185.00, 196.00, 207.65, 220.00, 233.08, 246.94,
    261.63, 277.18, 293.66, 311.13, 329.63, 349.23,
    369.99, 392.00, 415.30, 440.00, 466.16, 493.88,
    523.25, 554.37, 587.33, 622.25, 659.25, 698.46,
    739.99, 783.99, 830.61, 880.00, 932.33, 987.77,
    1046.50, 1108.73, 1174.66, 1244.51, 1318.51, 1396.91,
    1479.98, 1567.98, 1661.22, 1760.00, 1864.66, 1975.53,
    2093.00, 2217.46, 2349.32, 2489.02, 2637.02, 2793.83,
    2959.96, 3135.96, 3322.44, 3520.00, 3729.31, 3951.07
])

def remix_audio(input_audio,target_sr=None,norm=False,to_int16=False,resample=False,to_mono=False,axis=0,**kwargs):
    audio = np.array(input_audio[0],dtype="float32")
    if target_sr is None: target_sr=input_audio[1]

    print(f"before remix: shape={audio.shape}, max={audio.max()}, min={audio.min()}, mean={audio.mean()} sr={input_audio[1]}")
    if resample or input_audio[1]!=target_sr:
        audio = librosa.core.resample(np.array(input_audio[0],dtype="float32"),orig_sr=input_audio[1],target_sr=target_sr,**kwargs)
    
    if to_mono and audio.ndim>1: audio=np.nanmedian(audio,axis)

    if norm: audio = librosa.util.normalize(audio)

    audio_max = np.abs(audio).max() / 0.95
    if audio_max > 1: audio /= audio_max
    
    if to_int16: audio = np.clip(audio * MAX_INT16, a_min=-MAX_INT16+1, a_max=MAX_INT16-1).astype("int16")
    else: audio = audio.astype("float32")
    print(f"after remix: shape={audio.shape}, max={audio.max()}, min={audio.min()}, mean={audio.mean()}, sr={target_sr}")

    return audio, target_sr

def load_input_audio(fname,sr=None,**kwargs):
    sound = librosa.load(fname,sr=sr,**kwargs)
    print(f"loading sound {fname} {sound[0].shape} {sound[1]}")
    return sound
   
def save_input_audio(fname,input_audio,sr=None,to_int16=False):
    print(f"saving sound to {fname}")
    os.makedirs(os.path.dirname(fname),exist_ok=True)
    audio=np.array(input_audio[0],dtype="int16" if np.abs(input_audio[0]).max()>1 else "float32")
    if to_int16:
        max_a = np.abs(audio).max() * .99
        if max_a<1:
            audio=(audio*max_a*MAX_INT16)
        audio=audio.astype("int16")
    try:        
        sf.write(fname, audio, sr if sr else input_audio[1])
        return f"File saved to ${fname}"
    except Exception as e:
        return f"failed to save audio: {e}"
    
def audio_to_bytes(audio,sr,format='WAV'):
    bytes_io = io.BytesIO()
    sf.write(bytes_io, audio, sr, format=format)
    return bytes_io.read()

def bytes_to_audio(data: Union[io.BytesIO,bytes],**kwargs):
    if type(data)==bytes: bytes_io=io.BytesIO(data)
    else:
        bytes_io = data
        bytes_io.seek(0)

    # audio,sr = librosa.load(bytes_io)
    audio, sr = sf.read(bytes_io,**kwargs)
    if audio.ndim>1:
        if audio.shape[-1]<audio.shape[0]: # is channel-last format
            audio = audio.T # transpose to channels-first
    return audio, sr

def pad_audio(*audios,axis=0):
    maxlen = max(len(a) for a in audios if a is not None)
    stack = librosa.util.stack([librosa.util.pad_center(a,maxlen) for a in audios if a is not None],axis=axis)
    return stack

def merge_audio(audio1,audio2,sr=40000):
    print(f"merging audio audio1={audio1[0].shape,audio1[1]} audio2={audio2[0].shape,audio2[1]} sr={sr}")
    m1,_=remix_audio(audio1,target_sr=sr)
    m2,_=remix_audio(audio2,target_sr=sr)
    
    mixed = pad_audio(m1,m2)

    return remix_audio((mixed,sr),to_int16=True,norm=True,to_mono=True,axis=0)

def autotune_f0(f0, threshold=0.):
    print("autotuning f0 using note_dict...")

    autotuned_f0 = []
    # Loop through each value in array1
    for freq in f0:
        # Find the absolute difference between x and each value in array2
        diff = np.abs(AUTOTUNE_NOTES - freq)
        # Find the index of the minimum difference
        idx = np.argmin(diff)
        # Find the corresponding value in array2
        y = AUTOTUNE_NOTES[idx]
        # Check if the difference is less than threshold
        if diff[idx] < threshold:
            # Keep the value in array1
            autotuned_f0.append(freq)
        else:
            # Use the nearest value in array2
            autotuned_f0.append(y)
    # Return the result as a numpy array
    return np.array(autotuned_f0, dtype="float32")

def join_and_split_audio(list_of_dicts,role_mapper=None):
    # Initialize an empty AudioSegment to store the combined audio
    combined_audio = AudioSegment.empty()

    # Create a list to store timestamps
    timestamps = []

    # Iterate through the list of dicts
    for data_dict in list_of_dicts:
        # Extract audio file name and role from the dictionary
        audio = data_dict.get("audio")
        role = role_mapper(data_dict.get("role")) if role_mapper else data_dict.get("role")
        content = data_dict.get("content")

        if audio is not None:
            audio_data, sr = audio

            # Load the audio file using pydub
            audio_segment = AudioSegment(audio_data, sample_width=audio_data.dtype.itemsize, frame_rate=sr, channels=1)

            # Append the audio segment to the combined audio
            combined_audio += audio_segment

            # Calculate the timestamp for the end of this segment
            timestamp = len(combined_audio) / 1000  # Convert milliseconds to seconds
        
            timestamps.append({"role": role, "content": content, "timestamp": timestamp})
        else: timestamps.append({"role": role, "content": content})

    # Export the combined audio to a single file
    return combined_audio, timestamps
