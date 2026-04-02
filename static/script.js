// ====================== THREE.JS 3D JARVIS CORE ======================
let scene, camera, renderer;
let coreMesh, ring1, ring2, ring3, particleSystem;
let isListening = false;
let isSpeaking = false;

function initThree() {
    const canvas = document.getElementById('three-canvas');
    
    scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x0a0a1f, 10, 25);

    camera = new THREE.PerspectiveCamera(62, window.innerWidth / window.innerHeight, 0.1, 100);
    camera.position.set(0, 1, 7);

    renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // Lighting
    scene.add(new THREE.AmbientLight(0x00f7ff, 0.7));
    
    const p1 = new THREE.PointLight(0x00ffea, 3, 50);
    p1.position.set(8, 8, 8);
    scene.add(p1);
    
    const p2 = new THREE.PointLight(0x00f7ff, 2.5, 50);
    p2.position.set(-8, -8, -8);
    scene.add(p2);

    // Central Core
    const coreGeo = new THREE.SphereGeometry(1.25, 64, 64);
    const coreMat = new THREE.MeshPhongMaterial({
        color: 0x00f7ff,
        emissive: 0x00ffea,
        emissiveIntensity: 1.4,
        shininess: 120,
        transparent: true,
        opacity: 0.95
    });
    coreMesh = new THREE.Mesh(coreGeo, coreMat);
    scene.add(coreMesh);

    // Rotating Rings
    const ringMat = new THREE.MeshPhongMaterial({
        color: 0x00ffea,
        emissive: 0x00f7ff,
        transparent: true,
        opacity: 0.8
    });

    ring1 = new THREE.Mesh(new THREE.TorusGeometry(2.4, 0.08, 32, 100), ringMat);
    ring1.rotation.x = Math.PI / 2;
    scene.add(ring1);

    ring2 = new THREE.Mesh(new THREE.TorusGeometry(3.1, 0.06, 32, 100), ringMat);
    ring2.rotation.x = Math.PI / 3;
    scene.add(ring2);

    ring3 = new THREE.Mesh(new THREE.TorusGeometry(3.8, 0.05, 32, 100), ringMat);
    ring3.rotation.x = -Math.PI / 4;
    scene.add(ring3);

    // Particles
    const particleCount = 2000;
    const positions = new Float32Array(particleCount * 3);
    const colors = new Float32Array(particleCount * 3);

    for (let i = 0; i < particleCount * 3; i += 3) {
        const r = 4 + Math.random() * 1.5;
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        
        positions[i]     = r * Math.sin(phi) * Math.cos(theta);
        positions[i + 1] = r * Math.sin(phi) * Math.sin(theta);
        positions[i + 2] = r * Math.cos(phi);
        
        colors[i] = 0.6; colors[i+1] = 0.95; colors[i+2] = 1;
    }

    const pGeo = new THREE.BufferGeometry();
    pGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    pGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    particleSystem = new THREE.Points(pGeo, new THREE.PointsMaterial({
        size: 0.04,
        vertexColors: true,
        transparent: true,
        blending: THREE.AdditiveBlending,
        opacity: 0.9
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

    coreMesh.scale.setScalar(1 + Math.sin(t * 8) * 0.07);

    ring1.rotation.z = t * 0.7;
    ring2.rotation.z = -t * 1.4;
    ring3.rotation.z = t * 0.95;

    particleSystem.rotation.y = t * 0.3;

    if (isListening) particleSystem.rotation.y = t * 4;
    if (isSpeaking) coreMesh.rotation.y = t * 2;

    renderer.render(scene, camera);
}

// ====================== BACKEND COMMUNICATION ======================
function addToChat(sender, text) {
    const log = document.getElementById('chat-log');
    const div = document.createElement('div');
    div.className = `chat-message ${sender === 'user' ? 'user-msg' : 'assistant-msg'}`;
    div.innerHTML = `<small>${sender.toUpperCase()} • ${new Date().toLocaleTimeString('en-IN', {hour:'numeric', minute:'2-digit'})}</small><br>${text}`;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;

    if (log.children.length > 15) log.removeChild(log.children[0]);
}

async function sendQuery(query) {
    if (!query.trim()) return;

    addToChat('user', query);
    document.getElementById('core-text').textContent = 'PROCESSING...';

    try {
        const res = await fetch('/process', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query })
        });

        const data = await res.json();
        const reply = data.reply || "Sorry sir, I couldn't process that.";

        addToChat('assistant', reply);
        document.getElementById('response-text').innerHTML = reply;

        isSpeaking = true;
        setTimeout(() => {
            isSpeaking = false;
            document.getElementById('core-text').textContent = 'SAARTHI';
        }, 4500);

    } catch (e) {
        addToChat('assistant', 'Backend connection error.');
        document.getElementById('response-text').textContent = 'Connection failed.';
    }
}

// ====================== VOICE + UI ======================
let recognition;

function initVoice() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    recognition = new SpeechRecognition();
    recognition.lang = 'en-IN';
    recognition.interimResults = false;

    recognition.onstart = () => {
        isListening = true;
        document.getElementById('mic-btn').classList.add('listening');
        document.getElementById('core-text').innerHTML = 'LISTENING...';
    };

    recognition.onresult = (e) => {
        const transcript = e.results[0][0].transcript;
        sendQuery(transcript);
    };

    recognition.onend = () => {
        isListening = false;
        document.getElementById('mic-btn').classList.remove('listening');
    };
}

function setupUI() {
    const micBtn = document.getElementById('mic-btn');
    const textInput = document.getElementById('text-input');
    const sendBtn = document.getElementById('send-btn');

    micBtn.addEventListener('click', () => {
        if (recognition) recognition.start();
    });

    sendBtn.addEventListener('click', () => {
        sendQuery(textInput.value.trim());
        textInput.value = '';
    });

    textInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendQuery(textInput.value.trim());
            textInput.value = '';
        }
    });
}

// ====================== INITIALIZE ======================
window.onload = () => {
    initThree();
    initVoice();
    setupUI();

    // Welcome
    setTimeout(() => {
        addToChat('assistant', 'Saarthi 3D Interface activated. Your full Python backend is connected.');
    }, 800);
};