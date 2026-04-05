// ====================== THREE.JS 3D JARVIS CORE ======================
let scene, camera, renderer;
let coreMesh, ring1, ring2, ring3, particleSystem;
let isListening = false;
let isSpeaking = false;

function initThree() {
    const canvas = document.getElementById('three-canvas');

    scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x0a0a1f, 8, 28);

    camera = new THREE.PerspectiveCamera(62, window.innerWidth / window.innerHeight, 0.1, 100);
    camera.position.set(0, 1.2, 7.5);

    renderer = new THREE.WebGLRenderer({
        canvas: canvas,
        antialias: true,
        alpha: true
    });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    scene.add(new THREE.AmbientLight(0x00f7ff, 0.8));

    const p1 = new THREE.PointLight(0x00ffea, 3.5, 60);
    p1.position.set(10, 10, 10);
    scene.add(p1);

    const p2 = new THREE.PointLight(0x00f7ff, 2.8, 60);
    p2.position.set(-10, -10, -10);
    scene.add(p2);

    const coreGeo = new THREE.SphereGeometry(1.25, 64, 64);
    const coreMat = new THREE.MeshPhongMaterial({
        color: 0x00f7ff,
        emissive: 0x00ffea,
        emissiveIntensity: 1.5,
        shininess: 100,
        transparent: true,
        opacity: 0.96
    });
    coreMesh = new THREE.Mesh(coreGeo, coreMat);
    scene.add(coreMesh);

    const ringMat = new THREE.MeshPhongMaterial({
        color: 0x00ffea,
        emissive: 0x00f7ff,
        transparent: true,
        opacity: 0.75
    });

    ring1 = new THREE.Mesh(new THREE.TorusGeometry(2.45, 0.085, 32, 120), ringMat);
    ring1.rotation.x = Math.PI / 2;
    scene.add(ring1);

    ring2 = new THREE.Mesh(new THREE.TorusGeometry(3.15, 0.065, 32, 120), ringMat);
    ring2.rotation.x = Math.PI / 3;
    scene.add(ring2);

    ring3 = new THREE.Mesh(new THREE.TorusGeometry(3.85, 0.055, 32, 120), ringMat);
    ring3.rotation.x = -Math.PI / 4;
    scene.add(ring3);

    const particleCount = 2500;
    const positions = new Float32Array(particleCount * 3);

    for (let i = 0; i < particleCount * 3; i += 3) {
        const r = 4.2 + Math.random() * 2;
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);

        positions[i] = r * Math.sin(phi) * Math.cos(theta);
        positions[i + 1] = r * Math.sin(phi) * Math.sin(theta);
        positions[i + 2] = r * Math.cos(phi);
    }

    const pGeo = new THREE.BufferGeometry();
    pGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));

    particleSystem = new THREE.Points(pGeo, new THREE.PointsMaterial({
        size: 0.035,
        color: 0x00f7ff,
        transparent: true,
        opacity: 0.85
    }));
    scene.add(particleSystem);

    window.addEventListener('resize', () => {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
    });

    animateThree();
}

function animateThree() {
    requestAnimationFrame(animateThree);
    const t = Date.now() * 0.001;

    const pulse = 1 + Math.sin(t * 7) * 0.08;
    coreMesh.scale.setScalar(pulse);
    coreMesh.material.emissiveIntensity = 1.5 + Math.sin(t * 14) * 0.4;

    ring1.rotation.z = t * 0.65;
    ring2.rotation.z = -t * 1.35;
    ring3.rotation.z = t * 0.92;
    particleSystem.rotation.y = t * 0.25;

    if (isListening) {
        particleSystem.rotation.y = t * 5;
        coreMesh.material.emissiveIntensity = 2.5;
    }

    if (isSpeaking) {
        coreMesh.rotation.y = t * 2.5;
    }

    renderer.render(scene, camera);
}

// ====================== CHAT ======================
function addToChat(sender, text) {
    const log = document.getElementById('chat-log');
    const div = document.createElement('div');

    div.className = sender === 'user' ? 'normal-msg' : 'normal-msg';
    div.innerHTML = `<b>${sender === 'user' ? 'You' : 'Saarthi'}:</b> ${text}`;

    log.appendChild(div);
    log.scrollTop = log.scrollHeight;

    if (log.children.length > 30) {
        log.removeChild(log.children[0]);
    }
}

// ====================== SEND QUERY ======================
async function sendQuery(query) {
    if (!query.trim()) return;

    document.getElementById('text-input').value = "";
    document.getElementById('core-text').textContent = 'PROCESSING...';

    try {
        const res = await fetch('/process', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query })
        });

        const data = await res.json();

        // 🔥 Sync full chat (no duplicates)
        const log = document.getElementById('chat-log');
        log.innerHTML = "";

        data.chat.forEach(item => {
            addToChat('user', item.user);
            addToChat('assistant', item.assistant);
        });

        document.getElementById('response-text').innerHTML = data.reply;

        isSpeaking = true;
        setTimeout(() => {
            isSpeaking = false;
            document.getElementById('core-text').textContent = 'SAARTHI';
        }, 4000);

    } catch (e) {
        addToChat('assistant', 'Server error');
    }
}

// ====================== CHAT HISTORY LOAD ======================
async function fetchChat() {
    try {
        const res = await fetch('/get-chat');
        const data = await res.json();

        const log = document.getElementById('chat-log');
        log.innerHTML = "";

        data.chat.forEach(item => {
            addToChat('user', item.user);
            addToChat('assistant', item.assistant);
        });

    } catch (e) {}
}

// ====================== BACKEND LOGS ======================
function addBackendLog(text) {
    const log = document.getElementById('chat-log');
    const div = document.createElement('div');

    div.className = "backend-log";
    div.textContent = text;

    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}

async function fetchLogs() {
    try {
        const res = await fetch('/get-logs');
        const data = await res.json();

        data.logs.forEach(log => addBackendLog(log));

    } catch (e) {}
}

// ====================== CLEAR LOGS ======================
async function clearBackendLogs() {
    await fetch('/clear-logs');
    document.getElementById('chat-log').innerHTML = "";
}

// ====================== VOICE ======================
let recognition;

function initVoice() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    recognition = new SpeechRecognition();
    recognition.lang = 'en-IN';

    recognition.onstart = () => isListening = true;

    recognition.onresult = (e) => {
        const text = e.results[0][0].transcript;
        sendQuery(text);
    };

    recognition.onend = () => isListening = false;
}

// ====================== UI ======================
function setupUI() {
    document.getElementById('send-btn').onclick = () => {
        sendQuery(document.getElementById('text-input').value);
    };

    document.getElementById('text-input').addEventListener('keypress', e => {
        if (e.key === 'Enter') {
            sendQuery(e.target.value);
        }
    });

    document.getElementById('mic-btn').onclick = () => {
        if (recognition) recognition.start();
    };
}

// ====================== INIT ======================
window.onload = () => {
    initThree();
    initVoice();
    setupUI();

    fetchChat();
    setInterval(fetchLogs, 2000);

    setTimeout(() => {
        addToChat('assistant', 'Saarthi is online. Ready to assist you.');
    }, 1000);
};