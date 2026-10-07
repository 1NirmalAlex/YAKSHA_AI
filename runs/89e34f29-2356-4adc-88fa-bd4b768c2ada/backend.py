from flask import Flask, Response

app = Flask(__name__)

@app.route('/')
def index():
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Procedural 3D Car Driving Game</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <!-- Tailwind CSS CDN -->
        <link href="https://cdn.jsdelivr.net/npm/tailwindcss@3.3.2/dist/tailwind.min.css" rel="stylesheet">
        <!-- Three.js CDN -->
        <script src="https://cdn.jsdelivr.net/npm/three@0.152.2/build/three.min.js"></script>
        <style>
            body, html { margin: 0; height: 100%; overflow: hidden; }
            #scene-container { width: 100%; height: 100%; }
        </style>
    </head>
    <body class="bg-gray-900">
        <div id="scene-container"></div>
        <script>
            // Basic Three.js setup
            const container = document.getElementById('scene-container');
            const scene = new THREE.Scene();
            const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
            const renderer = new THREE.WebGLRenderer({ antialias: true });
            renderer.setSize(window.innerWidth, window.innerHeight);
            container.appendChild(renderer.domElement);

            // Simple geometry for placeholder
            const geometry = new THREE.BoxGeometry();
            const material = new THREE.MeshStandardMaterial({ color: 0x00ff00 });
            const cube = new THREE.Mesh(geometry, material);
            scene.add(cube);

            // Lighting
            const light = new THREE.DirectionalLight(0xffffff, 1);
            light.position.set(5, 10, 7.5);
            scene.add(light);

            camera.position.z = 5;

            function animate() {
                requestAnimationFrame(animate);
                cube.rotation.x += 0.01;
                cube.rotation.y += 0.01;
                renderer.render(scene, camera);
            }

            animate();

            // Handle resize
            window.addEventListener('resize', () => {
                const width = window.innerWidth;
                const height = window.innerHeight;
                renderer.setSize(width, height);
                camera.aspect = width / height;
                camera.updateProjectionMatrix();
            });
        </script>
    </body>
    </html>
    """
    return Response(html, mimetype='text/html')