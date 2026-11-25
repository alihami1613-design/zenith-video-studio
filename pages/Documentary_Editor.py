
import streamlit as st
import tempfile
import subprocess
import imageio_ffmpeg
from pathlib import Path

st.title("🎬 ZENITH DOCUMENTARY EDITOR")
st.caption("ZENITH BEYOND | Documentary Production Studio")

st.markdown("---")

st.subheader("01 — Upload Video Scenes")
st.write("Upload your video clips in the order you want them to appear.")

videos = st.file_uploader(
    "Select video clips",
    type=["mp4", "mov", "mkv", "avi", "webm"],
    accept_multiple_files=True,
    key="video_scenes"
)

st.markdown("---")

st.subheader("02 — Audio")

narration = st.file_uploader(
    "Upload narration (optional)",
    type=["mp3", "wav", "m4a", "aac", "ogg"],
    key="narration"
)

music = st.file_uploader(
    "Upload background music (optional)",
    type=["mp3", "wav", "m4a", "aac", "ogg"],
    key="music"
)

st.info(
    "Narration volume: 100% | Background music volume: 18%. "
    "When both are uploaded, the audio is mixed automatically."
)

st.markdown("---")

st.subheader("03 — Export Settings")

st.write("Output format: MP4")
st.write("Resolution: 1920 × 1080")
st.write("Frame rate: 30 FPS")
st.write("Video codec: H.264")

st.markdown("---")

if st.button("🎬 CREATE DOCUMENTARY", type="primary", use_container_width=True):

    if not videos:
        st.error("Please upload at least one video scene.")
        st.stop()

    if len(videos) > 20:
        st.error("Please upload no more than 20 scenes at a time.")
        st.stop()

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    progress = st.progress(0)
    status = st.empty()

    try:
        with tempfile.TemporaryDirectory() as temp_folder:

            work = Path(temp_folder)
            normalized_files = []

            # Step 1: Normalize all video scenes
            for index, uploaded_video in enumerate(videos):

                input_path = work / f"input_{index:03d}"
                input_path.write_bytes(uploaded_video.getbuffer())

                output_path = work / f"scene_{index:03d}.mp4"

                status.write(
                    f"Processing scene {index + 1} of {len(videos)}..."
                )

                command = [
                    ffmpeg,
                    "-y",
                    "-i", str(input_path),
                    "-vf",
                    "scale=1920:1080:force_original_aspect_ratio=decrease,"
                    "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
                    "setsar=1,fps=30,format=yuv420p",
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-crf", "23",
                    "-an",
                    "-movflags", "+faststart",
                    str(output_path)
                ]

                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=600
                )

                normalized_files.append(output_path)

                progress.progress(
                    int(((index + 1) / len(videos)) * 50)
                )

            # Step 2: Create the video sequence
            status.write("Combining video scenes...")

            concat_file = work / "concat.txt"

            with concat_file.open("w", encoding="utf-8") as file:
                for scene in normalized_files:
                    safe_path = scene.as_posix().replace("'", "'\\''")
                    file.write(f"file '{safe_path}'\n")

            combined_video = work / "combined.mp4"

            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(concat_file),
                    "-c", "copy",
                    str(combined_video)
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=600
            )

            progress.progress(65)

            # Step 3: Prepare final export
            final_video = work / "ZENITH_DOCUMENTARY.mp4"

            command = [
                ffmpeg,
                "-y",
                "-i", str(combined_video)
            ]

            audio_inputs = []

            if narration:
                narration_path = work / f"narration.{narration.name.rsplit('.', 1)[-1]}"
                narration_path.write_bytes(narration.getbuffer())
                command.extend(["-i", str(narration_path)])
                audio_inputs.append("narration")

            if music:
                music_path = work / f"music.{music.name.rsplit('.', 1)[-1]}"
                music_path.write_bytes(music.getbuffer())
                command.extend(["-i", str(music_path)])
                audio_inputs.append("music")

            # Step 4: Mix audio and extend the last frame when needed
            if narration and music:
                filter_graph = (
                    "[1:a]volume=1.0[n];"
                    "[2:a]volume=0.18[m];"
                    "[n][m]amix=inputs=2:duration=first:"
                    "dropout_transition=2[a];"
                    "[0:v]tpad=stop_mode=clone:stop_duration=3600[v]"
                )
                command.extend([
                    "-filter_complex", filter_graph,
                    "-map", "[v]",
                    "-map", "[a]"
                ])

            elif narration:
                filter_graph = (
                    "[0:v]tpad=stop_mode=clone:stop_duration=3600[v]"
                )
                command.extend([
                    "-filter_complex", filter_graph,
                    "-map", "[v]",
                    "-map", "1:a",
                    "-af", "volume=1.0"
                ])

            elif music:
                filter_graph = (
                    "[0:v]tpad=stop_mode=clone:stop_duration=3600[v]"
                )
                command.extend([
                    "-filter_complex", filter_graph,
                    "-map", "[v]",
                    "-map", "1:a",
                    "-af", "volume=0.18"
                ])

            else:
                command.extend([
                    "-map", "0:v"
                ])

            command.extend([
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                "-shortest",
                str(final_video)
            ])

            status.write("Rendering final documentary...")

            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=1200
            )

            progress.progress(100)
            status.success("Documentary export completed!")

            st.markdown("---")
            st.subheader("04 — Final Documentary")

            st.video(str(final_video))

            st.download_button(
                label="⬇️ DOWNLOAD FINAL DOCUMENTARY",
                data=final_video.read_bytes(),
                file_name="ZENITH_BEYOND_DOCUMENTARY.mp4",
                mime="video/mp4",
                use_container_width=True
            )

    except subprocess.TimeoutExpired:
        st.error(
            "Rendering took too long. Try fewer or shorter video clips."
        )

    except subprocess.CalledProcessError as error:
        st.error("Video processing failed.")
        if error.stderr:
            st.code(error.stderr[-3000:])

    except Exception as error:
        st.error(f"An unexpected error occurred: {error}")

st.markdown("---")
st.caption("ZENITH BEYOND — Beyond the Visible.")
