// ====================== THREE.JS 3D JARVIS CORE - Updated ======================
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

    // Lighting - Enhanced
    scene.add(new THREE.AmbientLight(0x00f7ff, 0.8));
    
    const p1 = new THREE.PointLight(0x00ffea, 3.5, 60);
    p1.position.set(10, 10, 10);
    scene.add(p1);
    
    const p2 = new THREE.PointLight(0x00f7ff, 2.8, 60);
    p2.position.set(-10, -10, -10);
    scene.add(p2);

    // Central Core
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

    // Rotating Rings
    const ringMat = new THREE.MeshPhongMaterial({
        color: 0x00ffea,
        emissive: 0x00f7ff,
        transparent: true,
        opacity: 0.75,
        shininess: 80
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

    // Particles - More dense and vibrant
    const particleCount = 2500;
    const positions = new Float32Array(particleCount * 3);
    const colors = new Float32Array(particleCount * 3);

    for (let i = 0; i < particleCount * 3; i += 3) {
        const r = 4.2 + Math.random() * 2;
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        
        positions[i]     = r * Math.sin(phi) * Math.cos(theta);
        positions[i + 1] = r * Math.sin(phi) * Math.sin(theta);
        positions[i + 2] = r * Math.cos(phi);
        
        colors[i] = 0.55; 
        colors[i+1] = 0.92; 
        colors[i+2] = 1.0;
    }

    const pGeo = new THREE.BufferGeometry();
    pGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    pGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    particleSystem = new THREE.Points(pGeo, new THREE.PointsMaterial({
        size: 0.035,
        vertexColors: true,
        transparent: true,
        blending: THREE.AdditiveBlending,
        opacity: 0.85
    }));
    scene.add(particleSystem);

    // Resize Handler
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

    // Core breathing effect
    const pulse = 1 + Math.sin(t * 7) * 0.08;
    coreMesh.scale.setScalar(pulse);
    
    // Dynamic emissive glow
    coreMesh.material.emissiveIntensity = 1.5 + Math.sin(t * 14) * 0.4;

    // Ring rotations
    ring1.rotation.z = t * 0.65;
    ring2.rotation.z = -t * 1.35;
    ring3.rotation.z = t * 0.92;

    // Particle rotation
    particleSystem.rotation.y = t * 0.25;

    // Special states
    if (isListening) {
        particleSystem.rotation.y = t * 5.5;
        coreMesh.material.emissiveIntensity = 2.8;
    }
    
    if (isSpeaking) {
        coreMesh.rotation.y = t * 2.8;
    }

    renderer.render(scene, camera);
}

// ====================== CHAT & BACKEND ======================
function addToChat(sender, text) {
    const log = document.getElementById('chat-log');
    const div = document.createElement('div');
    div.className = `chat-message ${sender === 'user' ? 'user-msg' : 'assistant-msg'}`;
    
    const time = new Date().toLocaleTimeString('en-IN', { 
        hour: 'numeric', 
        minute: '2-digit' 
    });
    
    div.innerHTML = `<small>${sender.toUpperCase()} • ${time}</small><br>${text}`;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;

    // Keep only last 15 messages
    if (log.children.length > 15) {
        log.removeChild(log.children[0]);
    }
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

        if (!res.ok) throw new Error('Server error');

        const data = await res.json();
        const reply = data.reply || "Sorry sir, I couldn't process that request.";

        addToChat('assistant', reply);
        document.getElementById('response-text').innerHTML = reply.replace(/\n/g, '<br>');

        isSpeaking = true;
        setTimeout(() => {
            isSpeaking = false;
            document.getElementById('core-text').textContent = 'SAARTHI';
        }, 5000);

    } catch (e) {
        console.error(e);
        addToChat('assistant', 'Backend connection error. Please check if server is running.');
        document.getElementById('response-text').textContent = 'Connection failed. Try again.';
    }
}

// ====================== VOICE RECOGNITION ======================
let recognition;

function initVoice() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        console.warn("Speech Recognition not supported in this browser.");
        return;
    }

    recognition = new SpeechRecognition();
    recognition.lang = 'en-IN';
    recognition.interimResults = false;
    recognition.continuous = false;

    recognition.onstart = () => {
        isListening = true;
        document.getElementById('mic-btn').classList.add('listening');
        document.getElementById('core-text').innerHTML = 'LISTENING<span style="animation: pulse 1.5s infinite;">...</span>';
    };

    recognition.onresult = (e) => {
        const transcript = e.results[0][0].transcript.trim();
        if (transcript) sendQuery(transcript);
    };

    recognition.onerror = (e) => {
        console.error("Speech recognition error:", e);
        isListening = false;
        document.getElementById('mic-btn').classList.remove('listening');
        document.getElementById('core-text').textContent = 'SAARTHI';
    };

    recognition.onend = () => {
        isListening = false;
        document.getElementById('mic-btn').classList.remove('listening');
        document.getElementById('core-text').textContent = 'SAARTHI';
    };
}

// ====================== UI SETUP ======================
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

    // Welcome Message after login
    setTimeout(() => {
        addToChat('assistant', 'Saarthi 3D Interface activated successfully.<br>Welcome back, Sir.');
        document.getElementById('response-text').innerHTML = 'Hello Sir, I am online and ready.<br>How may I assist you today?';
    }, 1200);
};