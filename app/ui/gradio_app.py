import json
from pathlib import Path

import gradio as gr
import requests

API = 'http://127.0.0.1:8000'


def _parse_response(resp: requests.Response) -> dict:
    try:
        payload = resp.json()
        if isinstance(payload, dict):
            return payload
        return {'status_code': resp.status_code, 'data': payload}
    except Exception:
        return {
            'status_code': resp.status_code,
            'error': 'non_json_response',
            'text': resp.text[:3000],
        }


def create_voice(name, description, files):
    files_payload = []
    handles = []
    try:
        for f in files:
            handle = open(f, 'rb')
            handles.append(handle)
            files_payload.append(('samples', (Path(f).name, handle)))
        r = requests.post(f'{API}/v1/voices', data={'name': name, 'description': description}, files=files_payload, timeout=120)
        return _parse_response(r)
    finally:
        for h in handles:
            h.close()


def run_preview(voice_id, text):
    r = requests.post(f'{API}/v1/voices/{voice_id}/preview', json={'text': text}, timeout=60)
    return _parse_response(r)


def run_train(voice_id, profile_name):
    r = requests.post(f'{API}/v1/voices/{voice_id}/train', json={'profile_name': profile_name}, timeout=60)
    return _parse_response(r)


def list_profiles(voice_id):
    r = requests.get(f'{API}/v1/voices/{voice_id}/profiles', timeout=30)
    return json.dumps(_parse_response(r), ensure_ascii=False, indent=2)


def run_tts(voice_id, profile_id, text, mode, fmt, speed, use_acc, use_ovr):
    payload = {
        'voice_id': voice_id,
        'profile_id': profile_id or None,
        'text': text,
        'mode': mode,
        'format': fmt,
        'speed': speed,
        'use_accenting': use_acc,
        'use_user_overrides': use_ovr,
    }
    r = requests.post(f'{API}/v1/tts', json=payload, timeout=60)
    return _parse_response(r)


def get_job(job_id):
    r = requests.get(f'{API}/v1/jobs/{job_id}', timeout=30)
    return json.dumps(_parse_response(r), ensure_ascii=False, indent=2)


with gr.Blocks(title='Voice AI') as demo:
    gr.Markdown('# Russian Voice AI MVP')
    with gr.Tab('Voices'):
        name = gr.Textbox(label='Voice name')
        descr = gr.Textbox(label='Description')
        samples = gr.File(file_count='multiple', label='Samples (.wav/.mp3/.m4a/.ogg)')
        out_create = gr.JSON(label='Create voice result')
        gr.Button('Create voice').click(create_voice, [name, descr, samples], out_create)

    with gr.Tab('Preview/Train'):
        voice_id = gr.Textbox(label='Voice ID')
        preview_text = gr.Textbox(value='Привет! Это быстрый тест.', label='Preview text')
        out_preview = gr.JSON(label='Preview job')
        gr.Button('Run preview').click(run_preview, [voice_id, preview_text], out_preview)

        profile_name = gr.Textbox(value='profile-1', label='Profile name')
        out_train = gr.JSON(label='Train job')
        gr.Button('Train profile').click(run_train, [voice_id, profile_name], out_train)
        profiles_out = gr.Textbox(label='Profiles')
        gr.Button('List profiles').click(list_profiles, [voice_id], profiles_out)

    with gr.Tab('TTS'):
        t_voice = gr.Textbox(label='Voice ID')
        t_profile = gr.Textbox(label='Profile ID (optional)')
        t_text = gr.Textbox(lines=8, label='Text')
        t_mode = gr.Dropdown(['story', 'poem'], value='story', label='Mode')
        t_fmt = gr.Dropdown(['wav', 'mp3'], value='wav', label='Format')
        t_speed = gr.Slider(0.5, 1.5, value=1.0, step=0.05, label='Speed')
        t_acc = gr.Checkbox(value=True, label='Use accenting')
        t_ovr = gr.Checkbox(value=True, label='Use user overrides')
        out_tts = gr.JSON(label='TTS job')
        gr.Button('Run TTS').click(run_tts, [t_voice, t_profile, t_text, t_mode, t_fmt, t_speed, t_acc, t_ovr], out_tts)

    with gr.Tab('Jobs'):
        j_id = gr.Textbox(label='Job ID')
        j_info = gr.Textbox(lines=12, label='Job status')
        gr.Button('Get job').click(get_job, [j_id], j_info)

if __name__ == '__main__':
    demo.launch(server_name='0.0.0.0', server_port=7860)
