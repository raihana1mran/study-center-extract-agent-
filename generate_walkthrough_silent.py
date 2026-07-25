"""
generate_walkthrough_silent.py — Standalone Walkthrough Video Compiler (Silent, No Captions)
For personal use. Automatically records the dashboard and merges it with custom slide intros/outros.
"""

import os
import sys
import time
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

# Paths
BASE_DIR = Path(__file__).parent
REPORTS_DIR = BASE_DIR / "reports"
TEMP_DIR = REPORTS_DIR / "temp_silent"
OUTPUT_VIDEO = REPORTS_DIR / "silent_walkthrough.mp4"
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

# Ensure directories exist
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)


class SilentVideoCompiler:
    def __init__(self, target_url="http://127.0.0.1:5000", project_name="NIOS Study Centre Collection Agent"):
        self.target_url = target_url
        self.project_name = project_name
        self.screenshot_path = TEMP_DIR / "dashboard_screenshot.png"
        self.recorded_video_path = TEMP_DIR / "raw_walkthrough.webm"

    def record_browser_session(self):
        """Use Playwright to run the live dashboard walkthrough and record the browser window."""
        print("Starting Playwright walkthrough recording...")
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # Launch browser with recording enabled
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--window-size=1920,1080",
                    "--disable-blink-features=AutomationControlled",
                ]
            )
            
            # Setup context with 1080p viewport and video recording
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                record_video_dir=str(TEMP_DIR),
                record_video_size={"width": 1920, "height": 1080}
            )
            
            page = context.new_page()
            
            try:
                print(f"Navigating to dashboard at {self.target_url}...")
                page.goto(self.target_url, timeout=45000)
                page.wait_for_timeout(3000)
                
                # Take screenshot for slide backgrounds
                page.screenshot(path=str(self.screenshot_path))
                print(f"Captured dashboard background: {self.screenshot_path}")
                
                # Step 1: Browse page & scroll centres
                print("Step 1: Navigating to Browse data view...")
                page.click("#nav-browser")
                page.wait_for_timeout(2000)
                
                # Scroll the table
                print("Scrolling table...")
                page.evaluate("window.scrollBy(0, 400)")
                page.wait_for_timeout(1500)
                page.evaluate("window.scrollBy(0, 400)")
                page.wait_for_timeout(1500)
                
                # Step 2: Go to Control panel and start a clean scrape
                print("Step 2: Going to Control panel...")
                page.click("#nav-control")
                page.wait_for_timeout(2000)
                
                # Trigger scrape
                print("Waiting for state options to load...")
                page.wait_for_function("document.querySelectorAll('#scrape-state option').length > 1")
                print("Triggering scrape run...")
                page.select_option("#scrape-state", value="9135") # Andaman and Nicobar
                page.wait_for_timeout(1000)
                page.click("#btn-start-scrape")
                
                # Wait to watch console logs scroll
                print("Watching console logs update...")
                page.wait_for_timeout(22000)
                
                # Step 3: Go to Reports Hub
                print("Step 3: Navigating to Reports Hub...")
                page.click("#nav-reports")
                page.wait_for_timeout(3000)
                
                # Step 4: Clean database
                print("Step 4: Cleaning database...")
                page.click("#nav-control")
                page.wait_for_timeout(1500)
                page.click("#btn-clear-db")
                page.wait_for_timeout(2000)
                
                # Back to dashboard
                page.click("#nav-dashboard")
                page.wait_for_timeout(3000)
                
            except Exception as e:
                print(f"Error during browser recording: {e}")
            finally:
                context.close()
                browser.close()
        
        # Locate recorded video
        recorded_files = list(TEMP_DIR.glob("*.webm"))
        if recorded_files:
            # Rename the webm file to a fixed name
            os.replace(recorded_files[0], self.recorded_video_path)
            print(f"Recorded video saved to: {self.recorded_video_path}")
            return True
        else:
            print("Failed to record video file.")
            return False

    def draw_rounded_rect(self, draw, xy, corner_radius, fill):
        """Helper to draw rounded rectangles on PIL canvas."""
        draw.rounded_rectangle(xy, radius=corner_radius, fill=fill)

    def generate_slide_images(self):
        """Render high-end presentation slides using PIL."""
        print("Generating premium slides...")
        
        # Load screenshot as background base if available
        bg_base = None
        if self.screenshot_path.exists():
            bg_base = Image.open(self.screenshot_path).resize((1920, 1080))
            # Apply dark mask
            mask = Image.new("RGBA", (1920, 1080), (15, 15, 26, 215)) # 84% translucent
            bg_base = Image.alpha_composite(bg_base.convert("RGBA"), mask)

        # Fallback dark background
        fallback_bg = Image.new("RGBA", (1920, 1080), (15, 15, 26, 255))
        
        # Slides configs
        slides = {
            "slide_1_intro.png": {
                "use_screenshot": True,
                "title": "Study Center Data Extraction\nAI Agent",
                "subtitle": "Generative AI & Agentic Workflow Demonstration",
                "badge": "PRODUCTION READY",
                "footer": "Presented by Raihana — AI Solutions Architect"
            },
            "slide_2_problem.png": {
                "use_screenshot": True,
                "title": "The Business Problem",
                "subtitle": "Manual Data Entry Inefficiencies",
                "badge": " friction & overhead ",
                "bullets": [
                    "• High Operational Labor Cost",
                    "• Incomplete Records & Bad Formats",
                    "• Slow Lead Generation Pipelines"
                ]
            },
            "slide_7_architecture.png": {
                "use_screenshot": False,
                "title": "System Architecture Diagram",
                "subtitle": "Multi-Agent Backend Workflow",
                "draw_diagram": True
            },
            "slide_8_agents.png": {
                "use_screenshot": False,
                "title": "Specialized AI Agents Cluster",
                "subtitle": "Collaborative Execution Model",
                "badge": "AGENTIC INTELLIGENCE",
                "bullets": [
                    "• Orchestrator Agent — Workflow Coordinator",
                    "• Planning Agent — Dynamic Chunking & Map",
                    "• Validation Agent — Integrity & Schema Compliance",
                    "• Memory Agent — State Persistence"
                ]
            },
            "slide_9_techstack.png": {
                "use_screenshot": False,
                "title": "Classification, Stack & Valuation",
                "subtitle": "BPA AI Agent MVP Metrics",
                "badge": "PROJECT ESTIMATION",
                "bullets": [
                    "• Classification: BPA Agent (MVP Stage)",
                    "• Core Stack: Python, Flask, Playwright, SQL",
                    "• Development Valuation: $9,500 – $18,000 USD",
                    "• Freelancer Rate: $75 – $150 / Hour (Senior Developer)"
                ]
            },
            "slide_10_cta.png": {
                "use_screenshot": True,
                "title": "Let's Automate Your Business",
                "subtitle": "Bring enterprise-grade AI automation to your custom workflows",
                "badge": "GET IN TOUCH",
                "footer": "Custom AI Agent Solutions | Contact: Raihana"
            }
        }

        # Fonts definition
        try:
            title_font = ImageFont.truetype("arial.ttf", 64)
            subtitle_font = ImageFont.truetype("arial.ttf", 32)
            bullet_font = ImageFont.truetype("arial.ttf", 28)
            badge_font = ImageFont.truetype("arial.ttf", 18)
        except IOError:
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
            bullet_font = ImageFont.load_default()
            badge_font = ImageFont.load_default()

        for filename, cfg in slides.items():
            img = bg_base.copy() if (cfg["use_screenshot"] and bg_base) else fallback_bg.copy()
            draw = ImageDraw.Draw(img)
            
            # Draw gradient line at the bottom
            draw.rectangle([(0, 1070), (1920, 1080)], fill=(0, 242, 254, 255))
            
            # Draw Badge
            if "badge" in cfg:
                badge_text = cfg["badge"].upper()
                # Badge container
                self.draw_rounded_rect(draw, [100, 150, 360, 185], 8, (0, 242, 254, 30))
                draw.text((120, 158), badge_text, font=badge_font, fill=(0, 242, 254, 255))
                
            # Draw Titles
            draw.text((100, 220), cfg["title"], font=title_font, fill=(255, 255, 255, 255))
            draw.text((100, 370), cfg["subtitle"], font=subtitle_font, fill=(0, 242, 254, 255))
            
            # Draw Bullets
            if "bullets" in cfg:
                y = 480
                for bullet in cfg["bullets"]:
                    draw.text((100, y), bullet, font=bullet_font, fill=(220, 220, 240, 255))
                    y += 60
                    
            # Draw custom architecture diagram
            if cfg.get("draw_diagram"):
                # Draw boxes for architecture representation
                boxes = [
                    ("User Frontend", 100, 500, 320, 580),
                    ("API Gateway", 380, 500, 600, 580),
                    ("Orchestrator", 660, 500, 880, 580),
                    ("Agents Cluster", 940, 420, 1220, 660),
                    ("APIs / DB", 1280, 500, 1500, 580),
                    ("Reports Output", 1560, 500, 1820, 580)
                ]
                for text, x1, y1, x2, y2 in boxes:
                    self.draw_rounded_rect(draw, [x1, y1, x2, y2], 12, (26, 26, 46, 255))
                    draw.rectangle([(x1, y1), (x2, y1+5)], fill=(0, 242, 254, 255)) # top colored accent border
                    draw.text((x1+20, y1+28), text, font=badge_font, fill=(255, 255, 255, 255))
                    
                # Draw simple flow lines
                draw.line([(320, 540), (380, 540)], fill=(0, 242, 254, 255), width=3)
                draw.line([(600, 540), (660, 540)], fill=(0, 242, 254, 255), width=3)
                draw.line([(880, 540), (940, 540)], fill=(0, 242, 254, 255), width=3)
                draw.line([(1220, 540), (1280, 540)], fill=(0, 242, 254, 255), width=3)
                draw.line([(1500, 540), (1560, 540)], fill=(0, 242, 254, 255), width=3)

            # Draw Footer
            if "footer" in cfg:
                draw.text((100, 950), cfg["footer"], font=subtitle_font, fill=(180, 180, 200, 255))

            # Save image
            img.convert("RGB").save(TEMP_DIR / filename)
            print(f"Generated slide: {filename}")

    def compile_clips(self):
        """Stitch slides to video clips, slice walkthrough cuts, and merge them all cleanly."""
        print("Compiling video clips...")
        
        # Segment definitions: (type, source, duration)
        segments = [
            ("slide", "slide_1_intro.png", 10),
            ("slide", "slide_2_problem.png", 10),
            ("walkthrough", 0, 8),          # Segment 3: dashboard load
            ("walkthrough", 8, 12),         # Segment 4: trigger scrape
            ("walkthrough", 20, 22),        # Segment 5: logs scroll
            ("walkthrough", 42, 10),        # Segment 6: reports view
            ("slide", "slide_7_architecture.png", 12),
            ("slide", "slide_8_agents.png", 12),
            ("slide", "slide_9_techstack.png", 12),
            ("slide", "slide_10_cta.png", 10)
        ]

        segment_files = []
        
        for idx, (seg_type, src, duration) in enumerate(segments, start=1):
            out_clip = TEMP_DIR / f"compiled_seg_{idx}.mp4"
            
            if seg_type == "slide":
                # Convert slide image to video loop
                slide_img = TEMP_DIR / src
                print(f"Compiling Slide Segment {idx} ({duration}s)...")
                
                # Check for zoom effect in workflow/tech slides (Segment 7 & 9)
                if idx in [7, 9]:
                    # Ken burns zoom effect
                    cmd = [
                        FFMPEG_EXE, "-y", "-loop", "1", "-i", str(slide_img),
                        "-vf", f"zoompan=z='min(zoom+0.0005,1.15)':d={duration*30}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080",
                        "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(out_clip)
                    ]
                else:
                    # Regular loop
                    cmd = [
                        FFMPEG_EXE, "-y", "-loop", "1", "-i", str(slide_img),
                        "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(out_clip)
                    ]
            else:
                # Cut section from recorded Playwright WebM session
                start_time = src
                print(f"Slicing Walkthrough Segment {idx} ({duration}s starting at {start_time}s)...")
                cmd = [
                    FFMPEG_EXE, "-y", "-ss", str(start_time), "-i", str(self.recorded_video_path),
                    "-t", str(duration), "-vf", "scale=1920:1080", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", str(out_clip)
                ]
                
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            segment_files.append(out_clip)

        # Merge segments using Concat Demuxer
        print("Concatenating final segments...")
        concat_txt = TEMP_DIR / "concat_list.txt"
        with open(concat_txt, "w") as f:
            for filepath in segment_files:
                clean_path = str(filepath.resolve()).replace("\\", "/")
                f.write(f"file '{clean_path}'\n")

        # Compile final output
        cmd = [
            FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt),
            "-c:v", "copy", str(OUTPUT_VIDEO)
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("Walkthrough video merged successfully!")
        
    def cleanup(self):
        """Remove temp directory files."""
        print("Cleaning up temporary clips...")
        for f in TEMP_DIR.glob("*"):
            try:
                os.remove(f)
            except Exception:
                pass
        try:
            os.rmdir(TEMP_DIR)
        except Exception:
            pass


def main():
    print("======================================================================")
    print("      STANDALONE WALKTHROUGH VIDEO COMPILER (SILENT & NO CAPTIONS)    ")
    print("======================================================================")
    
    # 1. Initialize
    compiler = SilentVideoCompiler()
    
    # 2. Record Playwright Walkthrough (Ensure Flask app is running first on 127.0.0.1:5000)
    success = compiler.record_browser_session()
    if not success:
        print("\n[ERROR] Playwright could not record browser dashboard walkthrough.")
        print("[TIP] Ensure Flask server is running locally (python app.py) before running this script.")
        sys.exit(1)
        
    # 3. Generate Slides
    compiler.generate_slide_images()
    
    # 4. Stitch and Merge
    compiler.compile_clips()
    
    # 5. Cleanup
    compiler.cleanup()
    
    print("======================================================================")
    print(f" SUCCESS: Silent demo video compiled successfully at:")
    print(f" {OUTPUT_VIDEO}")
    print("======================================================================")


if __name__ == "__main__":
    main()
