import json

def main():
    # Load Yangtze high-res coordinates
    with open("/Users/kansen/Documents/Code/Sanguozhi/scratch/yangtze.json", "r") as f:
        yangtze_coords = json.load(f)
        
    # Load Yellow River high-res coordinates
    with open("/Users/kansen/Documents/Code/Sanguozhi/scratch/yellow.json", "r") as f:
        yellow_coords = json.load(f)
        
    print(f"Loaded {len(yangtze_coords)} Yangtze points and {len(yellow_coords)} Yellow River points.")
    
    # Read current MapView.tsx
    with open("/Users/kansen/Documents/Code/Sanguozhi/frontend/src/app/components/MapView.tsx", "r") as f:
        content = f.read()
        
    # Locate where const RIVERS = [ starts and ends
    start_idx = content.find("const RIVERS = [")
    if start_idx == -1:
        print("Error: const RIVERS not found in MapView.tsx")
        return
        
    # Find the matching closing bracket for RIVERS array
    end_idx = content.find("];", start_idx)
    if end_idx == -1:
        print("Error: Closing bracket for RIVERS not found")
        return
    end_idx += 2 # include ];
    
    # Generate clean JavaScript array definition with ONLY Yangtze and Yellow River
    rivers_js = "const RIVERS = [\n"
    
    # 1. Yellow River (high-res)
    rivers_js += "  {\n"
    rivers_js += "    name: '黄河',\n"
    rivers_js += "    path: " + json.dumps(yellow_coords) + ",\n"
    rivers_js += "    width: 3.5,\n"
    rivers_js += "    color: [41, 128, 185, 220]\n"
    rivers_js += "  },\n"
    
    # 2. Yangtze River (high-res)
    rivers_js += "  {\n"
    rivers_js += "    name: '长江',\n"
    rivers_js += "    path: " + json.dumps(yangtze_coords) + ",\n"
    rivers_js += "    width: 3.5,\n"
    rivers_js += "    color: [41, 128, 185, 220]\n"
    rivers_js += "  }\n"
    
    rivers_js += "];"
    
    # Replace RIVERS in MapView.tsx
    new_content = content[:start_idx] + rivers_js + content[end_idx:]
    
    with open("/Users/kansen/Documents/Code/Sanguozhi/frontend/src/app/components/MapView.tsx", "w") as f:
        f.write(new_content)
        
    print("Successfully updated MapView.tsx with ONLY high-resolution Yangtze and Yellow River!")

if __name__ == "__main__":
    main()
