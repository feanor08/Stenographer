class Stenograph < Formula
  desc "Local audio transcription using Whisper — CLI"
  homepage "https://github.com/feanor08/Stenographer"
  version "1.0.8"

  on_macos do
    on_arm do
      url "https://github.com/feanor08/Stenographer/releases/download/v#{version}/stenograph-macos-arm64"
      sha256 :no_check   # updated automatically by CI
    end
    on_intel do
      url "https://github.com/feanor08/Stenographer/releases/download/v#{version}/stenograph-macos-x86_64"
      sha256 :no_check   # updated automatically by CI
    end
  end

  depends_on "ffmpeg"

  def install
    bin.install "stenograph-macos-#{Hardware::CPU.arch}" => "stenograph"
  end

  test do
    assert_match "Usage", shell_output("#{bin}/stenograph --help")
  end
end
