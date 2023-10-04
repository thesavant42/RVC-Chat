import os
import weakref
import streamlit as st
from webui import MENU_ITEMS, config, get_cwd, i18n, DEVICE_OPTIONS
from webui.chat import Character
from webui.downloader import OUTPUT_DIR
st.set_page_config(layout="wide",menu_items=MENU_ITEMS)

from webui.components import file_uploader_form
import sounddevice as sd
from webui.contexts import SessionStateContext
import time
from webui.utils import get_filenames, get_index, get_optimal_torch_device, ObjectNamespace, gc_collect, get_cache

CWD = get_cwd()

def get_model_list():
    models_list =  [os.path.relpath(path,CWD) for path in get_filenames(root=os.path.join(CWD,"models"),folder="LLM",exts=["bin","gguf"])]
    return models_list

def get_voice_list():
    models_list = [os.path.relpath(path,CWD) for path in get_filenames(root=os.path.join(CWD,"models"),folder="RVC",exts=["pth"])]
    return models_list

def get_character_list():
    models_list =  [os.path.relpath(path,CWD) for path in get_filenames(root=os.path.join(CWD,"models"),folder="Characters",exts=["json"])]
    return models_list

def init_state():
    state = ObjectNamespace(
        voice_models=get_voice_list(),
        characters=get_character_list(),
        model_list=get_model_list(),
        messages = [],
        user = "User",
        memory=10,
        character=None,
        device=get_optimal_torch_device(),
    )
    return state

def refresh_data(state):
    state.model_list = get_model_list()
    state.voice_models = get_voice_list()
    state.characters = get_character_list()
    gc_collect()
    return state

# A cache that stores weak references to large objects
CHARACTER_CACHE = get_cache("CHARACTER_CACHE")

@st.cache_resource
def get_character(_state):
    key = "character"

    if key in CHARACTER_CACHE and CHARACTER_CACHE[key]:
        return CHARACTER_CACHE[key]

    character = Character(
        character_file=_state.get("selected_character"),
        model_file=_state.get("selected_llm"),
        user=_state.get("user"),
        device=_state.get("device")
    )
    
    CHARACTER_CACHE[key] = character
    _state.character = weakref.ref(character)
    return _state

if __name__=="__main__":
    with SessionStateContext("chat",init_state()) as state:

        st.title("RVC Chat")

        hint = st.empty()

        if st.button("Refresh Files"):
            state = refresh_data(state)
        col1, col2, col3 = st.columns(3)
        
        state.user = col1.text_input("Your Name", value=state.user)
        state.selected_character = col2.selectbox("Your state.character",
                                              options=state.characters,
                                              index=get_index(state.characters,state.selected_character),
                                              format_func=lambda x: os.path.basename(x))
        state.selected_llm = col3.selectbox("Choose a language model",
                                options=state.model_list,
                                index=get_index(state.model_list,state.selected_llm),
                                format_func=lambda x: os.path.basename(x))
        
        with col1:
            c1, c2 = st.columns(2)
            state.device = c1.radio(
                i18n("inference.device"),
                disabled=not config.has_gpu,
                options=DEVICE_OPTIONS,horizontal=True,
                index=get_index(DEVICE_OPTIONS,state.device))
            
            if c2.button("Start Chatting",disabled=not (state.selected_character and state.selected_llm and state.user),type="primary"):
                with st.spinner("Loading model..."):
                    if state.character:
                        state.character.load_character(state.selected_character)
                        state.character.user = state.user
                        state.character.loaded = True
                        
                        if hash(state.character.model_file)!=hash(state.selected_llm):
                            state.character.load_model(state.selected_llm)
                            state.character.unload()
                            st.toast(state.character.load())
                    else:
                        state = get_character(state)
                        if state.character and not state.character.loaded: st.toast(state.character.load())

        chat_disabled = state.character is None or not state.character.loaded
        if chat_disabled: hint.warning("Enter your name, select your state.character, and choose a language model to get started!")

        if not chat_disabled:

            # save/load chat history
            save_dir = os.path.join(OUTPUT_DIR,"chat",state.character.name)
            file_uploader_form(save_dir,title="Upload your chat history",types=["zip"])
            state.history_file = st.selectbox("Continue a saved chat history",options=[""]+get_filenames(root=save_dir,name_filters=["json"]))
            col1,col2, col3 = st.columns(3)

            if col1.button("Save Chat",disabled=not state.character):
                save_dir = os.path.dirname(state.history_file) if state.history_file else None
                st.toast(state.character.save_history(save_dir))
                state = refresh_data(state)

            if col2.button("Load Chat",disabled=not state.history_file):
                st.toast(state.character.load_history(state.history_file))
                state.user = state.character.user

            if col3.button("Clear Chat",type="primary",disabled=state.character is None or len(state.character.messages)==0):
                state.character.clear_chat()

            # display chat messages
            for i,msg in enumerate(state.character.messages):
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
                    col1, col2 = st.columns(2)
                    if msg.get("audio"):
                        if col1.button("Play",key=f"Play{i}"): sd.play(*msg["audio"])
                    if col2.button("Delete",key=f"Delete{i}"):
                        st.toast(f"Deleted message: {state.character.messages.pop(i)}")
                        st.experimental_rerun()

            # container = st.container()
            if st.button("Summarize Context"):
                st.write(state.character.summarize_context())
            if state.character.is_recording:
                if st.button("Stop Voice Chat",type="primary"):
                    state.character.is_recording=False
                    st.experimental_rerun()
                with st.spinner("Listening to mic..."):
                    time.sleep(1)
                    st.experimental_rerun()
            # elif st.button("Voice Chat (WIP)",type="secondary" ):
            #     state.character.speak_and_listen()
            #     st.experimental_rerun()
            elif st.button("Toggle Autoplay",type="primary" if state.character.autoplay else "secondary" ):
                state.character.toggle_autoplay()

            if prompt:=st.chat_input(disabled=chat_disabled or state.character.autoplay) or state.character.autoplay:
                state.character.is_recording=False
                if not state.character.autoplay:
                    st.chat_message(state.character.user).write(prompt)
                full_response = ""
                with st.chat_message(state.character.name):
                    message_placeholder = st.empty()
                    for response in state.character.generate_text("Continue the story without me" if state.character.autoplay else prompt):
                        full_response += response
                        message_placeholder.markdown(full_response)
                audio = state.character.text_to_speech(full_response)
                if audio: sd.play(*audio)
                if not state.character.autoplay:
                    state.character.messages.append({"role": state.character.user, "content": prompt}) #add user prompt to history
                state.character.messages.append({
                    "role": state.character.name,
                    "content": full_response,
                    "audio": audio
                    })
                if state.character.autoplay:
                    st.experimental_rerun()

            
            
        