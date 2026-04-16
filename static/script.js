// ====================== THREE.JS STATE ======================
let scene, camera, renderer;
let coreMesh, ring1, ring2, ring3, particleSystem;

let isListening = false;
let isSpeaking = false;

let appInitialized = false;
let isProcessing = false;

// prevent duplicates
let shownLogs = new Set();
let shownChat = new Set();

// ====================== LOAD CHAT ONLY ONCE ======================
function loadChatHistory() {
    fetch('/get-chat')
        .then(r => r.json())
        .then(data => {
            const chat = data.chat || [];

            chat.forEach(item => {
                const userKey = "u_" + item.user;
                const aiKey = "a_" + item.assistant;

                if (item.user && !shownChat.has(userKey)) {
                    addMessage('user', item.user);
                    shownChat.add(userKey);
                }

                if (item.assistant && !shownChat.has(aiKey)) {
                    addMessage('assistant', item.assistant);
                    shownChat.add(aiKey);
                }
            });
        })
        .catch(err => console.error("Chat load error:", err));
}

// ====================== THREE.JS INIT ======================
function initThree() {
    const canvas = document.getElementById('three-canvas');

    scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x0a0a1f, 8, 28);

    camera = new THREE.PerspectiveCamera(
        62,
        window.innerWidth / window.innerHeight,
        0.1,
        100
    );

    camera.position.set(0, 1.2, 7.5);

    renderer = new THREE.WebGLRenderer({
        canvas,
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

    // CORE
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

    // RINGS
    const ringMat = new THREE.MeshPhongMaterial({
        color: 0x00ffea,
        emissive: 0x00f7ff,
        transparent: true,
        opacity: 0.75
    });

    ring1 = new THREE.Mesh(new THREE.TorusGeometry(2.45, 0.085, 32, 120), ringMat);
    ring2 = new THREE.Mesh(new THREE.TorusGeometry(3.15, 0.065, 32, 120), ringMat);
    ring3 = new THREE.Mesh(new THREE.TorusGeometry(3.85, 0.055, 32, 120), ringMat);

    ring1.rotation.x = Math.PI / 2;
    ring2.rotation.x = Math.PI / 3;
    ring3.rotation.x = -Math.PI / 4;

    scene.add(ring1, ring2, ring3);

    // PARTICLES
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

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));

    particleSystem = new THREE.Points(
        geo,
        new THREE.PointsMaterial({
            size: 0.035,
            color: 0x00f7ff,
            transparent: true,
            opacity: 0.85
        })
    );

    scene.add(particleSystem);

    window.addEventListener('resize', () => {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
    });

    animate();
}

// ====================== ANIMATION ======================
function animate() {
    requestAnimationFrame(animate);

    const t = Date.now() * 0.001;

    coreMesh.scale.setScalar(1 + Math.sin(t * 7) * 0.08);
    coreMesh.material.emissiveIntensity = 1.5 + Math.sin(t * 14) * 0.4;

    ring1.rotation.z = t * 0.65;
    ring2.rotation.z = -t * 1.35;
    ring3.rotation.z = t * 0.92;

    particleSystem.rotation.y = isListening ? t * 5 : t * 0.25;

    renderer.render(scene, camera);
}

// ====================== CHAT UI ======================
function addMessage(sender, text) {
    const log = document.getElementById('chat-log');

    const div = document.createElement('div');
    div.classList.add('chat-message');

    if (sender === 'user') {
        div.classList.add('user-msg');
        div.innerHTML = `<strong>You:</strong> ${text}`;
    } else if (sender === 'assistant') {
        div.classList.add('assistant-msg');
        div.innerHTML = `<strong>Saarthi:</strong> ${text}`;
    } else {
        div.classList.add('backend-log');
        div.textContent = text;
    }

    log.appendChild(div);

    // smooth scroll (NO jump/disappear)
    setTimeout(() => {
        log.scrollTop = log.scrollHeight;
    }, 50);

    // limit memory
    if (log.children.length > 60) {
        log.removeChild(log.firstElementChild);
    }
}

// ====================== SEND QUERY ======================
async function sendQuery(query) {
    if (!query || !query.trim()) return;
    if (isProcessing) return;

    isProcessing = true;

    const input = document.getElementById('text-input');
    input.value = "";

    addMessage('user', query);

    document.getElementById('response-text').textContent = "Thinking...";

    try {
        const res = await fetch('/process', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ query: query.trim() })
        });

        const data = await res.json();

        if (data.reply) {
            addMessage('assistant', data.reply);
            document.getElementById('response-text').textContent = data.reply;
        }

    } catch (e) {
        addMessage('assistant', 'Server error');
    } finally {
        isProcessing = false;
    }
}

// ====================== LOGS (FIXED) ======================
async function fetchLogs() {
    try {
        const res = await fetch('/get-logs');
        const data = await res.json();

        (data.logs || []).forEach(log => {
            if (log && !shownLogs.has(log)) {
                addMessage('backend', log);
                shownLogs.add(log);
            }
        });

        if (shownLogs.size > 200) shownLogs.clear();

    } catch (e) {
        console.error(e);
    }
}

// ====================== MIC ======================
let micActive = false;

function updateMicUI(active) {
    micActive = active;
    isListening = active;

    const btn = document.getElementById('mic-btn');
    const badge = document.getElementById('mic-status-badge');
    const coreText = document.getElementById('core-text');

    if (active) {
        btn.textContent = '🔴';
        btn.classList.add('listening');
        badge.textContent = 'MIC ON';
        coreText.textContent = 'LISTENING...';
    } else {
        btn.textContent = '🎤';
        btn.classList.remove('listening');
        badge.textContent = 'MIC OFF';
        coreText.textContent = 'SAARTHI';
    }
}

async function toggleMic() {
    try {
        const res = await fetch('/toggle-mic', {method: 'POST'});
        const data = await res.json();
        updateMicUI(data.status === 'on');
    } catch (e) {
        console.error(e);
    }
}

// ====================== INIT ======================
window.onload = () => {
    if (appInitialized) return;
    appInitialized = true;

    initThree();
    loadChatHistory();

    document.getElementById('send-btn').onclick =
        () => sendQuery(document.getElementById('text-input').value);

    document.getElementById('mic-btn').onclick = toggleMic;

    setInterval(fetchLogs, 8000);

    setTimeout(() => {
        if (document.getElementById('chat-log').children.length === 0) {
            addMessage('assistant', 'Saarthi is online.');
        }
    }, 800);
};