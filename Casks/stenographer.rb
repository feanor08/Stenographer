cask "stenographer" do
  version "1.0.5"
  sha256 :no_check   # updated automatically by CI

  url "https://github.com/feanor08/Stenographer/releases/download/v#{version}/Stenographer-#{version}.dmg"
  name "Stenographer"
  desc "Local audio transcription using Whisper — GUI"
  homepage "https://github.com/feanor08/Stenographer"

  depends_on macos: ">= :big_sur"

  app "Stenographer.app"

  zap trash: [
    "~/Library/Logs/Stenographer",
    "~/.stenographer_settings.json",
  ]
end
