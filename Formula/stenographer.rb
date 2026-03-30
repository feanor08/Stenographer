class Stenographer < Formula
  desc "Local audio transcription using Whisper — CLI"
  homepage "https://github.com/feanor08/Stenographer"
  version "1.0.5"

  on_macos do
    on_arm do
      url "https://github.com/feanor08/Stenographer/releases/download/v#{version}/stenographer-macos-arm64"
      sha256 :no_check   # updated automatically by CI
    end
    on_intel do
      url "https://github.com/feanor08/Stenographer/releases/download/v#{version}/stenographer-macos-x86_64"
      sha256 :no_check   # updated automatically by CI
    end
  end

  depends_on "ffmpeg"

  def install
    bin.install "stenographer-macos-#{Hardware::CPU.arch}" => "stenographer"
  end

  test do
    assert_match "Usage", shell_output("#{bin}/stenographer --help")
  end
end
