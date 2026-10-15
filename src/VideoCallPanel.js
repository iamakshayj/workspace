import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CommunicationClient } from './communicationService';
import { appendMeetingCallArtifacts } from './enterpriseService';

function initials(name = '') {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || '?';
}

function uniqueId(prefix) {
  if (window.crypto?.randomUUID) return `${prefix}-${window.crypto.randomUUID()}`;
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function rtcConfiguration() {
  const configured = process.env.REACT_APP_WEBRTC_ICE_SERVERS;
  if (!configured) return { iceServers: [] };
  try {
    const iceServers = JSON.parse(configured);
    return { iceServers: Array.isArray(iceServers) ? iceServers : [] };
  } catch {
    return { iceServers: [] };
  }
}

function sameCall(event, call) {
  return event.call_id === call.callId
    && event.context?.kind === call.context.kind
    && event.context?.id === call.context.id;
}

function VideoTile({ user, stream, muted = false, label }) {
  const videoRef = useRef(null);
  useEffect(() => {
    if (videoRef.current) videoRef.current.srcObject = stream || null;
  }, [stream]);
  return <article className={`video-call-tile ${stream ? 'has-video' : ''}`}>
    <video ref={videoRef} autoPlay playsInline muted={muted} />
    {!stream && <span className="video-call-avatar" style={{ '--avatar-color': user.color || '#5b4be7' }}>{initials(user.display_name)}</span>}
    <footer><strong>{label || user.display_name}</strong>{muted && <span>You</span>}</footer>
  </article>;
}

function CameraIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 8H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-1l5 3V8l-5 3v-1a2 2 0 0 0-2-2Z" /></svg>;
}

function MicIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15a4 4 0 0 0 4-4V6a4 4 0 0 0-8 0v5a4 4 0 0 0 4 4Zm7-4a7 7 0 0 1-14 0M12 18v4M8 22h8" /></svg>;
}

function EndIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 15c4.8-4 11.2-4 16 0M7 13l-2 5M17 13l2 5" /></svg>;
}

function ShareIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12v8h16v-8M12 16V3M7 8l5-5 5 5" /></svg>;
}

const CALL_REACTIONS = ['👍', '👏', '❤️', '😂', '🎉'];

export function IncomingCallToast({ call, onAccept, onDecline }) {
  return <aside className="incoming-call-toast" role="dialog" aria-label={`Incoming call from ${call.user.display_name}`}>
    <span className="incoming-call-pulse"><CameraIcon /></span>
    <div><small>{call.context.kind === 'calendar' ? 'Meeting started' : 'Incoming call'}</small>
      <strong>{call.title || call.user.display_name}</strong><p>{call.user.display_name} · {call.media === 'audio' ? 'Audio' : 'Video'}</p></div>
    <button className="call-decline-button" aria-label="Decline call" onClick={onDecline}><EndIcon /></button>
    <button className="call-accept-button" aria-label="Accept call" onClick={onAccept}><CameraIcon /></button>
  </aside>;
}

export default function VideoCallPanel({ currentUser, call, onClose }) {
  const [stage, setStage] = useState('lobby');
  const [viewMode, setViewMode] = useState('mini');
  const [mediaMode, setMediaMode] = useState(call.media || 'video');
  const [localStream, setLocalStream] = useState(null);
  const [participants, setParticipants] = useState({});
  const [micEnabled, setMicEnabled] = useState(true);
  const [cameraEnabled, setCameraEnabled] = useState((call.media || 'video') === 'video');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const [devices, setDevices] = useState({ microphones: [], cameras: [] });
  const [selectedMicrophone, setSelectedMicrophone] = useState('');
  const [selectedCamera, setSelectedCamera] = useState('');
  const [screenSharing, setScreenSharing] = useState(false);
  const [sidePanel, setSidePanel] = useState('people');
  const [callMessages, setCallMessages] = useState([]);
  const [messageDraft, setMessageDraft] = useState('');
  const [notes, setNotes] = useState('');
  const [transcript, setTranscript] = useState([]);
  const [liveCaption, setLiveCaption] = useState('');
  const [captionsEnabled, setCaptionsEnabled] = useState(false);
  const [raisedHand, setRaisedHand] = useState(false);
  const [roomReactions, setRoomReactions] = useState([]);
  const [recording, setRecording] = useState(false);
  const [savingArtifacts, setSavingArtifacts] = useState(false);
  const [artifactsSaved, setArtifactsSaved] = useState(false);
  const [quality, setQuality] = useState({ label: 'Connecting', rtt: null, packetLoss: null });
  const [breakoutRooms, setBreakoutRooms] = useState([]);
  const clientIdRef = useRef(uniqueId('call-client'));
  const clientRef = useRef(null);
  const streamRef = useRef(null);
  const cameraTrackRef = useRef(null);
  const screenTrackRef = useRef(null);
  const peersRef = useRef(new Map());
  const candidateQueuesRef = useRef(new Map());
  const joinedRef = useRef(false);
  const invitedRef = useRef(false);
  const recognitionRef = useRef(null);
  const recorderRef = useRef(null);
  const recordingChunksRef = useRef([]);
  const forceLeaveRef = useRef(null);
  const callRef = useRef(call);
  callRef.current = call;
  const isHost = call.isHost !== false && call.ring !== false;

  const loadDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      const available = await navigator.mediaDevices.enumerateDevices();
      const microphones = available.filter((device) => device.kind === 'audioinput');
      const cameras = available.filter((device) => device.kind === 'videoinput');
      setDevices({ microphones, cameras });
      setSelectedMicrophone((current) => current || microphones[0]?.deviceId || '');
      setSelectedCamera((current) => current || cameras[0]?.deviceId || '');
    } catch { /* Device labels remain unavailable until permission is granted. */ }
  }, []);

  useEffect(() => { loadDevices(); }, [loadDevices]);

  const send = useCallback((type, extra = {}) => clientRef.current?.send({
    type,
    call_id: callRef.current.callId,
    client_id: clientIdRef.current,
    context: callRef.current.context,
    media: mediaMode,
    title: callRef.current.title || '',
    ...extra,
  }), [mediaMode]);

  const removePeer = useCallback((remoteClientId) => {
    const peer = peersRef.current.get(remoteClientId);
    if (peer) peer.pc.close();
    peersRef.current.delete(remoteClientId);
    candidateQueuesRef.current.delete(remoteClientId);
    setParticipants((current) => {
      const next = { ...current };
      delete next[remoteClientId];
      return next;
    });
  }, []);

  const sendSignal = useCallback((peer, kind, data) => send('call_signal', {
    target_user_id: peer.user.id,
    target_client_id: peer.clientId,
    signal: { kind, data },
  }), [send]);

  const createPeer = useCallback((remoteClientId, user) => {
    const existing = peersRef.current.get(remoteClientId);
    if (existing) return existing;
    const pc = new RTCPeerConnection(rtcConfiguration());
    const peer = { pc, user, clientId: remoteClientId };
    peersRef.current.set(remoteClientId, peer);
    streamRef.current?.getTracks().forEach((track) => pc.addTrack(track, streamRef.current));
    setParticipants((current) => ({
      ...current,
      [remoteClientId]: {
        user, stream: null, state: 'connecting', micEnabled: true,
        cameraEnabled: true, screenSharing: false, raisedHand: false,
      },
    }));
    pc.onicecandidate = (event) => {
      if (event.candidate) sendSignal(peer, 'ice', event.candidate.toJSON ? event.candidate.toJSON() : event.candidate);
    };
    pc.ontrack = (event) => {
      const stream = event.streams?.[0] || new MediaStream([event.track]);
      setParticipants((current) => ({
        ...current,
        [remoteClientId]: {
          ...(current[remoteClientId] || {}), user, stream, state: 'connected',
        },
      }));
    };
    pc.onconnectionstatechange = () => {
      const connectionState = pc.connectionState;
      if (['failed', 'closed', 'disconnected'].includes(connectionState)) removePeer(remoteClientId);
      else setParticipants((current) => current[remoteClientId] ? {
        ...current, [remoteClientId]: { ...current[remoteClientId], state: connectionState },
      } : current);
    };
    return peer;
  }, [removePeer, sendSignal]);

  const applySignal = useCallback(async (event) => {
    if (event.target_client_id !== clientIdRef.current) return;
    const remoteClientId = event.client_id;
    const peer = createPeer(remoteClientId, event.user);
    const { kind, data } = event.signal;
    if (kind === 'offer') {
      await peer.pc.setRemoteDescription(data);
      const answer = await peer.pc.createAnswer();
      await peer.pc.setLocalDescription(answer);
      sendSignal(peer, 'answer', peer.pc.localDescription.toJSON ? peer.pc.localDescription.toJSON() : peer.pc.localDescription);
    } else if (kind === 'answer') {
      await peer.pc.setRemoteDescription(data);
    } else if (kind === 'ice') {
      if (peer.pc.remoteDescription) await peer.pc.addIceCandidate(data);
      else candidateQueuesRef.current.set(remoteClientId, [...(candidateQueuesRef.current.get(remoteClientId) || []), data]);
    }
    if (peer.pc.remoteDescription && candidateQueuesRef.current.has(remoteClientId)) {
      const queued = candidateQueuesRef.current.get(remoteClientId);
      candidateQueuesRef.current.delete(remoteClientId);
      await Promise.all(queued.map((candidate) => peer.pc.addIceCandidate(candidate)));
    }
  }, [createPeer, sendSignal]);

  const handleCallEvent = useCallback(async (event) => {
    if (event.type === 'call_error' && (!event.call_id || event.call_id === callRef.current.callId)) {
      setError(event.message || 'The call could not be updated.');
      return;
    }
    if (!sameCall(event, callRef.current)) return;
    try {
      if (event.type === 'call_participant_joined' && event.client_id !== clientIdRef.current) {
        const peer = createPeer(event.client_id, event.user);
        const offer = await peer.pc.createOffer();
        await peer.pc.setLocalDescription(offer);
        sendSignal(peer, 'offer', peer.pc.localDescription.toJSON ? peer.pc.localDescription.toJSON() : peer.pc.localDescription);
      } else if (event.type === 'call_signal') await applySignal(event);
      else if (event.type === 'call_participant_left') removePeer(event.client_id);
      else if (event.type === 'call_declined') setNotice(`${event.user.display_name} declined the call.`);
      else if (event.type === 'call_chat') setCallMessages((current) => [...current, {
        id: uniqueId('call-message'), body: event.body, user: event.user,
        createdAt: new Date().toISOString(),
      }]);
      else if (event.type === 'call_reaction') {
        const reaction = { id: uniqueId('reaction'), emoji: event.emoji, user: event.user };
        setRoomReactions((current) => [...current.slice(-5), reaction]);
        window.setTimeout(() => setRoomReactions((current) => current.filter((item) => item.id !== reaction.id)), 3500);
      } else if (event.type === 'call_hand') {
        setParticipants((current) => current[event.client_id] ? {
          ...current,
          [event.client_id]: { ...current[event.client_id], raisedHand: event.raised },
        } : current);
      } else if (event.type === 'call_caption') {
        setLiveCaption(`${event.user.display_name}: ${event.caption}`);
        if (event.final) setTranscript((current) => [...current, `${event.user.display_name}: ${event.caption}`]);
      } else if (event.type === 'call_state') {
        setParticipants((current) => current[event.client_id] ? {
          ...current,
          [event.client_id]: {
            ...current[event.client_id],
            micEnabled: event.state.mic_enabled,
            cameraEnabled: event.state.camera_enabled,
            screenSharing: event.state.screen_sharing,
          },
        } : current);
      } else if (event.type === 'call_recording') {
        setNotice(`${event.user.display_name} ${event.recording_state} local recording.`);
      } else if (event.type === 'call_breakout') {
        setBreakoutRooms(event.rooms || []);
        setNotice(`${event.user.display_name} prepared ${event.rooms?.length || 0} breakout rooms.`);
      } else if (event.type === 'call_control' && event.target_client_id === clientIdRef.current) {
        if (event.action === 'mute') {
          streamRef.current?.getAudioTracks().forEach((track) => { track.enabled = false; });
          setMicEnabled(false);
          setNotice(`${event.user.display_name} muted you.`);
        } else if (event.action === 'remove') {
          setError(`${event.user.display_name} removed you from the call.`);
          window.setTimeout(() => forceLeaveRef.current?.(), 500);
        }
      }
    } catch {
      setError('A secure media connection could not be established.');
    }
  }, [applySignal, createPeer, removePeer, sendSignal]);

  const cleanUp = useCallback(() => {
    if (joinedRef.current) send('call_leave');
    joinedRef.current = false;
    try { recognitionRef.current?.stop(); } catch { /* Recognition may already be stopped. */ }
    recognitionRef.current = null;
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
    recorderRef.current = null;
    peersRef.current.forEach(({ pc }) => pc.close());
    peersRef.current.clear();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    screenTrackRef.current?.stop();
    streamRef.current = null;
    cameraTrackRef.current = null;
    screenTrackRef.current = null;
    clientRef.current?.disconnect();
    clientRef.current = null;
  }, [send]);

  useEffect(() => () => cleanUp(), [cleanUp]);

  useEffect(() => {
    if (stage !== 'active') return undefined;
    const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [stage]);

  const join = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof RTCPeerConnection === 'undefined') {
      setError('This browser does not support secure audio and video calls.');
      return;
    }
    setStage('joining'); setError('');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: selectedMicrophone ? { deviceId: { exact: selectedMicrophone } } : true,
        video: mediaMode === 'video' ? (selectedCamera ? { deviceId: { exact: selectedCamera } } : true) : false,
      });
      streamRef.current = stream; setLocalStream(stream);
      cameraTrackRef.current = stream.getVideoTracks()[0] || null;
      loadDevices();
      setCameraEnabled(stream.getVideoTracks().some((track) => track.enabled));
      const client = new CommunicationClient({
        onStatus: (status) => {
          if (status !== 'connected') return;
          joinedRef.current = true;
          if (call.ring !== false && !invitedRef.current) {
            invitedRef.current = true;
            send('call_invite');
          }
          send('call_join');
          send('call_state', { state: {
            mic_enabled: true,
            camera_enabled: stream.getVideoTracks().some((track) => track.enabled),
            screen_sharing: false,
          } });
          setStage('active');
        },
        onEvent: handleCallEvent,
        onError: setError,
      });
      clientRef.current = client;
      client.connect();
    } catch (mediaError) {
      cleanUp();
      setStage('lobby');
      setError(mediaError?.name === 'NotAllowedError'
        ? 'Camera or microphone access was not allowed. You can update browser permissions and try again.'
        : 'Camera and microphone could not be started.');
    }
  };

  const saveArtifacts = async () => {
    if (call.context.kind !== 'calendar' || (!notes.trim() && transcript.length === 0)) return;
    setSavingArtifacts(true); setError('');
    try {
      await appendMeetingCallArtifacts(call.context.id, {
        notes: notes.trim(), transcript: transcript.join('\n'),
      });
      setArtifactsSaved(true);
      setNotice('Meeting notes and captions were saved to the meeting record.');
    } catch (saveError) {
      setError(saveError.message || 'Meeting artifacts could not be saved.');
    } finally {
      setSavingArtifacts(false);
    }
  };
  const leave = () => {
    if (!artifactsSaved && call.context.kind === 'calendar' && (notes.trim() || transcript.length)) {
      appendMeetingCallArtifacts(call.context.id, {
        notes: notes.trim(), transcript: transcript.join('\n'),
      }).catch(() => {});
    }
    cleanUp(); setStage('ended'); onClose();
  };
  forceLeaveRef.current = leave;
  const toggleMic = () => {
    const next = !micEnabled;
    streamRef.current?.getAudioTracks().forEach((track) => { track.enabled = next; });
    setMicEnabled(next);
    send('call_state', { state: { mic_enabled: next, camera_enabled: cameraEnabled, screen_sharing: screenSharing } });
  };
  const toggleCamera = () => {
    if (mediaMode !== 'video' || screenSharing) return;
    const next = !cameraEnabled;
    streamRef.current?.getVideoTracks().forEach((track) => { track.enabled = next; });
    setCameraEnabled(next);
    send('call_state', { state: { mic_enabled: micEnabled, camera_enabled: next, screen_sharing: false } });
  };
  const stopScreenShare = useCallback(async () => {
    const cameraTrack = cameraTrackRef.current;
    await Promise.all([...peersRef.current.values()].map(({ pc }) => {
      const sender = pc.getSenders().find((candidate) => candidate.track?.kind === 'video');
      return sender ? sender.replaceTrack(cameraTrack) : Promise.resolve();
    }));
    screenTrackRef.current?.stop(); screenTrackRef.current = null;
    const audioTracks = streamRef.current?.getAudioTracks() || [];
    const restored = new MediaStream([...audioTracks, ...(cameraTrack ? [cameraTrack] : [])]);
    streamRef.current = restored; setLocalStream(restored); setScreenSharing(false);
    send('call_state', { state: { mic_enabled: micEnabled, camera_enabled: Boolean(cameraTrack?.enabled), screen_sharing: false } });
  }, [micEnabled, send]);
  const toggleScreenShare = async () => {
    if (screenSharing) { await stopScreenShare(); return; }
    if (!navigator.mediaDevices?.getDisplayMedia) { setError('Screen sharing is not supported by this browser.'); return; }
    try {
      const display = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
      const track = display.getVideoTracks()[0];
      if (!track) return;
      screenTrackRef.current = track;
      const audioTracks = streamRef.current?.getAudioTracks() || [];
      const shared = new MediaStream([...audioTracks, track]);
      await Promise.all([...peersRef.current.values()].map(({ pc }) => {
        const sender = pc.getSenders().find((candidate) => candidate.track?.kind === 'video');
        if (sender) return sender.replaceTrack(track);
        pc.addTrack(track, shared);
        return Promise.resolve();
      }));
      streamRef.current = shared; setLocalStream(shared); setScreenSharing(true);
      send('call_state', { state: { mic_enabled: micEnabled, camera_enabled: true, screen_sharing: true } });
      track.onended = () => { stopScreenShare().catch(() => setError('Camera video could not be restored.')); };
    } catch (shareError) {
      if (shareError?.name !== 'NotAllowedError') setError('Your screen could not be shared.');
    }
  };

  const sendCallMessage = (event) => {
    event.preventDefault();
    const body = messageDraft.trim();
    if (!body) return;
    setCallMessages((current) => [...current, {
      id: uniqueId('call-message'), body, user: currentUser, createdAt: new Date().toISOString(),
    }]);
    send('call_chat', { body });
    setMessageDraft('');
  };
  const reactInCall = (emoji) => {
    const reaction = { id: uniqueId('reaction'), emoji, user: currentUser };
    setRoomReactions((current) => [...current.slice(-5), reaction]);
    send('call_reaction', { emoji });
    window.setTimeout(() => setRoomReactions((current) => current.filter((item) => item.id !== reaction.id)), 3500);
  };
  const toggleHand = () => {
    const next = !raisedHand;
    setRaisedHand(next); send('call_hand', { raised: next });
  };
  const toggleCaptions = () => {
    if (captionsEnabled) {
      try { recognitionRef.current?.stop(); } catch { /* Already stopped. */ }
      recognitionRef.current = null; setCaptionsEnabled(false); setLiveCaption(''); return;
    }
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setError('Live captions are not supported in this browser. Meeting notes and chat remain available.');
      return;
    }
    const recognition = new SpeechRecognition();
    recognition.continuous = true; recognition.interimResults = true; recognition.lang = 'en-US';
    recognition.onresult = (event) => {
      let interim = '';
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const text = event.results[index][0]?.transcript?.trim();
        if (!text) continue;
        if (event.results[index].isFinal) {
          setTranscript((current) => [...current, `${currentUser.display_name}: ${text}`]);
          setLiveCaption(`${currentUser.display_name}: ${text}`);
          send('call_caption', { caption: text, final: true });
        } else interim += `${text} `;
      }
      if (interim.trim()) {
        setLiveCaption(`${currentUser.display_name}: ${interim.trim()}`);
        send('call_caption', { caption: interim.trim(), final: false });
      }
    };
    recognition.onerror = () => { setCaptionsEnabled(false); setError('Live captions stopped unexpectedly.'); };
    recognition.onend = () => { recognitionRef.current = null; setCaptionsEnabled(false); };
    try { recognition.start(); recognitionRef.current = recognition; setCaptionsEnabled(true); }
    catch { setError('Live captions could not be started.'); }
  };
  const toggleRecording = () => {
    if (recording) {
      recorderRef.current?.stop();
      send('call_recording', { recording_state: 'stopped' });
      setRecording(false); return;
    }
    if (!window.MediaRecorder || !streamRef.current) {
      setError('Local recording is not supported by this browser.'); return;
    }
    if (!window.confirm('Start a local recording? Confirm that everyone in the call has consented.')) return;
    try {
      const recorder = new MediaRecorder(streamRef.current);
      recordingChunksRef.current = [];
      recorder.ondataavailable = (event) => { if (event.data?.size) recordingChunksRef.current.push(event.data); };
      recorder.onstop = () => {
        if (!recordingChunksRef.current.length) return;
        const blob = new Blob(recordingChunksRef.current, { type: recorder.mimeType || 'video/webm' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url; link.download = `${call.title.replace(/[^a-z0-9]+/gi, '-').toLowerCase() || 'meeting'}-${Date.now()}.webm`;
        link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      };
      recorder.start(1000); recorderRef.current = recorder; setRecording(true);
      send('call_recording', { recording_state: 'started' });
    } catch { setError('Local recording could not be started.'); }
  };
  const controlParticipant = (clientId, participant, action) => {
    send('call_control', {
      target_user_id: participant.user.id, target_client_id: clientId, action,
    });
    if (action === 'remove') removePeer(clientId);
  };
  const prepareBreakouts = () => {
    const userIds = participantList.map(([, participant]) => participant.user.id);
    if (userIds.length < 2) { setNotice('At least two other participants are needed for breakout rooms.'); return; }
    const rooms = [
      { name: 'Breakout 1', user_ids: userIds.filter((_, index) => index % 2 === 0) },
      { name: 'Breakout 2', user_ids: userIds.filter((_, index) => index % 2 === 1) },
    ].filter((room) => room.user_ids.length);
    setBreakoutRooms(rooms); send('call_breakout', { rooms }); setSidePanel('people');
    setNotice(`${rooms.length} breakout groups are ready for the facilitator.`);
  };
  const participantList = useMemo(() => Object.entries(participants), [participants]);
  const time = `${String(Math.floor(elapsed / 60)).padStart(2, '0')}:${String(elapsed % 60).padStart(2, '0')}`;

  useEffect(() => {
    if (stage !== 'active') return undefined;
    const inspect = async () => {
      const peerStats = await Promise.all([...peersRef.current.values()].map(async ({ pc }) => {
        let peerRtt = null; let peerLost = 0; let peerReceived = 0;
        try {
          const stats = await pc.getStats();
          stats.forEach((report) => {
            if (report.type === 'candidate-pair' && report.state === 'succeeded' && Number.isFinite(report.currentRoundTripTime)) peerRtt = Math.round(report.currentRoundTripTime * 1000);
            if (report.type === 'inbound-rtp' && !report.isRemote) {
              peerLost += Number(report.packetsLost || 0); peerReceived += Number(report.packetsReceived || 0);
            }
          });
        } catch { /* Quality remains unknown while a peer reconnects. */ }
        return { rtt: peerRtt, packetsLost: peerLost, packetsReceived: peerReceived };
      }));
      const measuredRtts = peerStats.map((item) => item.rtt).filter((value) => value !== null);
      const rtt = measuredRtts.length ? Math.max(...measuredRtts) : null;
      const packetsLost = peerStats.reduce((total, item) => total + item.packetsLost, 0);
      const packetsReceived = peerStats.reduce((total, item) => total + item.packetsReceived, 0);
      const packetLoss = packetsReceived + packetsLost > 0 ? Math.round((packetsLost / (packetsReceived + packetsLost)) * 100) : null;
      const label = participantList.length === 0 ? 'Ready' : (rtt !== null && rtt > 300) || (packetLoss !== null && packetLoss > 5) ? 'Weak' : 'Good';
      setQuality({ label, rtt, packetLoss });
    };
    inspect(); const timer = window.setInterval(inspect, 5000);
    return () => window.clearInterval(timer);
  }, [stage, participantList.length]);

  const collapsed = viewMode === 'collapsed';

  return <section className={`video-call-panel ${viewMode} stage-${stage}`} role="dialog" aria-modal="false" aria-label={`${call.title} call`}>
    <header><div><span className="video-call-live"><i /> {stage === 'active' ? 'Live' : 'Call lobby'}</span>
      <h2>{call.title}</h2><p>{call.context.kind === 'calendar' ? 'Scheduled team meeting' : call.context.kind === 'channel' ? 'Team conversation' : 'Direct conversation'}</p></div>
      <div>{stage === 'active' && <time>{time}</time>}
        {viewMode === 'collapsed' ? <button className="video-call-window-button" aria-label="Restore call window" title="Restore call window" onClick={() => setViewMode('mini')}>▣</button> : <>
          {viewMode === 'mini' && <button className="video-call-window-button" aria-label="Collapse call window" title="Collapse call window" onClick={() => setViewMode('collapsed')}>—</button>}
          <button className="video-call-window-button" aria-label={viewMode === 'expanded' ? 'Return call to mini window' : 'Expand call window'}
            title={viewMode === 'expanded' ? 'Return to mini window' : 'Expand call window'}
            onClick={() => setViewMode((current) => current === 'expanded' ? 'mini' : 'expanded')}>{viewMode === 'expanded' ? '↘' : '↗'}</button>
        </>}
        <button className="icon-button" aria-label={stage === 'active' ? 'Leave call' : 'Close call panel'} onClick={leave}>×</button></div></header>
    {!collapsed && (stage === 'lobby' || stage === 'joining' ? <div className="video-call-lobby">
      <VideoTile user={currentUser} stream={null} muted label={currentUser.display_name} />
      <div className="video-call-lobby-copy"><span className="video-call-lock">⌾</span><h3>Ready to join?</h3>
        <p>Your camera and microphone stay off until you select Join. Media is sent directly between participants.</p>
        <div className="video-call-mode" role="radiogroup" aria-label="Call mode">
          <button role="radio" aria-checked={mediaMode === 'video'} className={mediaMode === 'video' ? 'active' : ''} onClick={() => setMediaMode('video')}><CameraIcon /> Video</button>
          <button role="radio" aria-checked={mediaMode === 'audio'} className={mediaMode === 'audio' ? 'active' : ''} onClick={() => setMediaMode('audio')}><MicIcon /> Audio only</button>
        </div>
        {(devices.microphones.length > 0 || devices.cameras.length > 0) && <div className="video-device-selectors">
          {devices.microphones.length > 0 && <label>Microphone<select aria-label="Microphone" value={selectedMicrophone} onChange={(event) => setSelectedMicrophone(event.target.value)}>{devices.microphones.map((device, index) => <option value={device.deviceId} key={device.deviceId}>{device.label || `Microphone ${index + 1}`}</option>)}</select></label>}
          {mediaMode === 'video' && devices.cameras.length > 0 && <label>Camera<select aria-label="Camera" value={selectedCamera} onChange={(event) => setSelectedCamera(event.target.value)}>{devices.cameras.map((device, index) => <option value={device.deviceId} key={device.deviceId}>{device.label || `Camera ${index + 1}`}</option>)}</select></label>}
        </div>}
        {error && <p className="video-call-error" role="alert">{error}</p>}
        <button className="button primary video-call-join" disabled={stage === 'joining'} onClick={join}>{stage === 'joining' ? 'Connecting…' : 'Join now'}</button>
      </div>
    </div> : <div className="video-call-stage">
      <div className={`video-call-grid count-${Math.min(4, participantList.length + 1)}`}>
        <VideoTile user={currentUser} stream={cameraEnabled ? localStream : null} muted label={currentUser.display_name} />
        {participantList.map(([clientId, participant]) => <VideoTile key={clientId} user={participant.user} stream={participant.stream} />)}
        {participantList.length === 0 && <div className="video-call-waiting"><span>◎</span><strong>Waiting for others</strong><p>Invited participants can join from their incoming-call notification.</p></div>}
        {roomReactions.length > 0 && <div className="video-call-reaction-stage" aria-live="polite">{roomReactions.map((reaction) => <span key={reaction.id}><b>{reaction.emoji}</b><small>{reaction.user.display_name}</small></span>)}</div>}
        {liveCaption && <div className="video-call-caption" aria-live="polite">{liveCaption}</div>}
      </div>
      <aside className="video-call-sidebar">
        <nav aria-label="Call collaboration panels">
          <button className={sidePanel === 'people' ? 'active' : ''} onClick={() => setSidePanel('people')}>People <span>{participantList.length + 1}</span></button>
          <button className={sidePanel === 'chat' ? 'active' : ''} onClick={() => setSidePanel('chat')}>Chat {callMessages.length > 0 && <span>{callMessages.length}</span>}</button>
          <button className={sidePanel === 'notes' ? 'active' : ''} onClick={() => setSidePanel('notes')}>Notes</button>
        </nav>
        {sidePanel === 'people' && <div className="video-call-participants"><h3>In this call</h3>
          <div><span className="video-call-mini-avatar" style={{ '--avatar-color': currentUser.color }}>{initials(currentUser.display_name)}</span><strong>{currentUser.display_name}<small>You · {isHost ? 'Host' : 'Participant'}{raisedHand ? ' · ✋ Hand raised' : ''}</small></strong></div>
          {participantList.map(([clientId, participant]) => <div key={clientId}><span className="video-call-mini-avatar" style={{ '--avatar-color': participant.user.color }}>{initials(participant.user.display_name)}</span><strong>{participant.user.display_name}<small>{participant.state === 'connected' ? 'In call' : 'Connecting…'}{participant.raisedHand ? ' · ✋ Hand raised' : ''}{participant.screenSharing ? ' · Sharing' : ''}</small></strong>
            <span className="participant-media-state" title={participant.micEnabled ? 'Microphone on' : 'Muted'}>{participant.micEnabled ? '●' : '⊘'}</span>
            {isHost && <details className="participant-controls"><summary aria-label={`Manage ${participant.user.display_name}`}>•••</summary><div><button onClick={() => controlParticipant(clientId, participant, 'mute')}>Mute</button><button className="danger" onClick={() => controlParticipant(clientId, participant, 'remove')}>Remove</button></div></details>}
          </div>)}
          <section className="call-quality-card"><span className={quality.label.toLowerCase()} /> <strong>{quality.label} connection</strong><small>{quality.rtt === null ? 'Encrypted peer connection' : `${quality.rtt} ms latency`}{quality.packetLoss === null ? '' : ` · ${quality.packetLoss}% loss`}</small></section>
          {isHost && <button className="call-breakout-button" onClick={prepareBreakouts}>Split into breakout groups</button>}
          {breakoutRooms.length > 0 && <div className="call-breakout-list"><strong>Breakout plan</strong>{breakoutRooms.map((room) => <span key={room.name}>{room.name}<small>{room.user_ids.length} assigned</small></span>)}</div>}
        </div>}
        {sidePanel === 'chat' && <div className="video-call-chat">
          <div>{callMessages.length === 0 && <p className="video-call-empty">Share a link or message without leaving the call.</p>}{callMessages.map((message) => <article key={message.id}><span className="video-call-mini-avatar" style={{ '--avatar-color': message.user.color }}>{initials(message.user.display_name)}</span><div><strong>{message.user.display_name}<time>{new Date(message.createdAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</time></strong><p>{message.body}</p></div></article>)}</div>
          <form onSubmit={sendCallMessage}><textarea aria-label="Call message" value={messageDraft} maxLength="2000" onChange={(event) => setMessageDraft(event.target.value)} placeholder="Message everyone…" onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} /><button disabled={!messageDraft.trim()}>Send</button></form>
        </div>}
        {sidePanel === 'notes' && <div className="video-call-notes"><label>Shared meeting notes<textarea aria-label="Meeting notes" value={notes} onChange={(event) => { setNotes(event.target.value); setArtifactsSaved(false); }} placeholder="Capture decisions, risks, and action items…" /></label>
          <div className="call-transcript-preview"><strong>Live transcript <span>{transcript.length}</span></strong>{transcript.length === 0 ? <p>Turn on captions to build a searchable transcript.</p> : transcript.slice(-8).map((line, index) => <p key={`${line}-${index}`}>{line}</p>)}</div>
          {call.context.kind === 'calendar' ? <button className="call-save-notes" disabled={savingArtifacts || artifactsSaved || (!notes.trim() && transcript.length === 0)} onClick={saveArtifacts}>{savingArtifacts ? 'Saving…' : artifactsSaved ? 'Saved to meeting' : 'Save to meeting record'}</button> : <p className="call-notes-hint">Notes remain in this call window. Schedule a calendar meeting to store them in organizational memory.</p>}
        </div>}
      </aside>
    </div>)}
    {!collapsed && (notice || (stage === 'active' && error)) && <div className={`video-call-notice ${error ? 'error' : ''}`}>{error || notice}<button onClick={() => { setNotice(''); setError(''); }}>×</button></div>}
    {!collapsed && stage === 'active' && <footer className="video-call-controls">
      <button className={micEnabled ? '' : 'off'} aria-label={micEnabled ? 'Mute microphone' : 'Unmute microphone'} onClick={toggleMic}><MicIcon /><span>{micEnabled ? 'Mute' : 'Unmute'}</span></button>
      <button className={cameraEnabled ? '' : 'off'} disabled={mediaMode !== 'video'} aria-label={cameraEnabled ? 'Turn camera off' : 'Turn camera on'} onClick={toggleCamera}><CameraIcon /><span>{cameraEnabled ? 'Camera' : 'Camera off'}</span></button>
      <button className={screenSharing ? 'sharing' : ''} aria-label={screenSharing ? 'Stop sharing screen' : 'Share screen'} onClick={toggleScreenShare}><ShareIcon /><span>{screenSharing ? 'Stop share' : 'Share'}</span></button>
      <button className={raisedHand ? 'sharing' : ''} aria-label={raisedHand ? 'Lower hand' : 'Raise hand'} onClick={toggleHand}><span aria-hidden="true">✋</span><span>{raisedHand ? 'Lower hand' : 'Raise hand'}</span></button>
      <button className={captionsEnabled ? 'sharing' : ''} aria-label={captionsEnabled ? 'Turn captions off' : 'Turn captions on'} onClick={toggleCaptions}><span aria-hidden="true">CC</span><span>Captions</span></button>
      <details className="video-call-reactions"><summary aria-label="Send a reaction"><span aria-hidden="true">☺</span><span>React</span></summary><div>{CALL_REACTIONS.map((emoji) => <button key={emoji} aria-label={`React ${emoji}`} onClick={() => reactInCall(emoji)}>{emoji}</button>)}</div></details>
      <button className={recording ? 'recording' : ''} aria-label={recording ? 'Stop recording' : 'Start recording'} onClick={toggleRecording}><span aria-hidden="true">●</span><span>{recording ? 'Stop rec' : 'Record'}</span></button>
      <button className="end" aria-label="Leave call" onClick={leave}><EndIcon /><span>Leave</span></button>
    </footer>}
  </section>;
}
