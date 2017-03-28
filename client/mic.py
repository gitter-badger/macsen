# -*- coding: utf-8 -*-
"""
    The Mic class handles all interactions with the microphone and speaker.
"""
import logging
import tempfile
import wave
import audioop
import pyaudio
import alteration
import jasperpath

import wave
import datetime

class Mic:

    speechRec = None
    speechRec_persona = None

    def __init__(self, speaker, passive_stt_engine, active_stt_engine):
        """
        Initiates the pocketsphinx instance.

        Arguments:
        speaker -- handles platform-independent audio output
        passive_stt_engine -- performs STT while Jasper is in passive listen mode
        acive_stt_engine -- performs STT while Jasper is in active listen mode
        """
        self._logger = logging.getLogger(__name__)
        self.speaker = speaker
        self.passive_stt_engine = passive_stt_engine
        self.active_stt_engine = active_stt_engine
        self._logger.info("Initializing PyAudio. ALSA/Jack error messages " +
                          "that pop up during this process are normal and " +
                          "can usually be safely ignored.")
        self._audio = pyaudio.PyAudio()
        self._logger.info("Initialization of PyAudio completed.")

   
    def set_tts_default_voice(self, default_voice):
	self.speaker.default_voice(default_voice)
 
    def __del__(self):
        self._audio.terminate()

    def getScore(self, data):
        rms = audioop.rms(data, 2)
        score = rms / 3
        return score

    def fetchThreshold(self):

        # TODO: Consolidate variables from the next three functions
        # TODO: load a RATE from the profile. (bangor needs 48000)
        THRESHOLD_MULTIPLIER = 1.8
        RATE = 48000
        CHUNK = 1024

        # number of seconds to allow to establish threshold
        THRESHOLD_TIME = 1

        # prepare recording stream
        stream = self._audio.open(format=pyaudio.paInt16,
                                  channels=1,
                                  rate=RATE,
                                  input=True,
                                  frames_per_buffer=CHUNK)

        # stores the audio data
        frames = []

        # stores the lastN score values
        lastN = [i for i in range(20)]

        # calculate the long run average, and thereby the proper threshold
        for i in range(0, RATE / CHUNK * THRESHOLD_TIME):

            data = stream.read(CHUNK)
            frames.append(data)

            # save this data point as a score
            lastN.pop(0)
            lastN.append(self.getScore(data))
            average = sum(lastN) / len(lastN)

        stream.stop_stream()
        stream.close()

        # this will be the benchmark to cause a disturbance over!
        THRESHOLD = average * THRESHOLD_MULTIPLIER

        return THRESHOLD

    def passiveListen(self, PERSONA):

        """
        Listens for PERSONA in everyday sound. Times out after LISTEN_TIME, so
        needs to be restarted.
        """
        THRESHOLD = False
        self._logger.info("Passive Listen.....")  

        if self.passive_stt_engine.has_mic() is True:
            transcribed = self.passive_stt_engine.transcribe(None)
            if transcribed and len(transcribed) > 0:
                THRESHOLD = True
        else:
            # TODO: load a RATE from the profile. (bangor julius-cy needs 48000)
            THRESHOLD_MULTIPLIER = 1.8
            RATE = 48000
            CHUNK = 1024

            # number of seconds to allow to establish threshold
            THRESHOLD_TIME = 1

            # number of seconds to listen before forcing restart
            LISTEN_TIME = 10

            THRESHOLD=self.fetchThreshold()

            # prepare recording stream
            stream = self._audio.open(format=pyaudio.paInt16,
                                  channels=1,
                                  rate=RATE,
                                  input=True,
                                  frames_per_buffer=CHUNK)

            # save some memory for sound data
            frames = []

            # flag raised when sound disturbance detected
            didDetect = False

            # start passively listening for disturbance above threshold
            for i in range(0, RATE / CHUNK * LISTEN_TIME):

                data = stream.read(CHUNK)
                frames.append(data)
                score = self.getScore(data)

                if score > THRESHOLD:
                    didDetect = True
                    break

            # no use continuing if no flag raised
            if not didDetect:
                print "No disturbance detected"
                self._logger.info("No disturbance detected")
                stream.stop_stream()
                stream.close()
                return (None, None)

            # cutoff any recording before this disturbance was detected
            frames = frames[-20:]

            # otherwise, let's keep recording for few seconds and save the file
            DELAY_MULTIPLIER = 1
            for i in range(0, RATE / CHUNK * DELAY_MULTIPLIER):
                data = stream.read(CHUNK)
                frames.append(data)

            # save the audio data
            stream.stop_stream()
            stream.close()

            with tempfile.NamedTemporaryFile(mode='w+b') as f:
                wav_fp = wave.open(f, 'wb')
                wav_fp.setnchannels(1)
                wav_fp.setsampwidth(pyaudio.get_sample_size(pyaudio.paInt16))
                wav_fp.setframerate(RATE)
                wav_fp.writeframes(''.join(frames))
                wav_fp.close()
                f.seek(0)
                # check if PERSONA was said
                transcribed = self.passive_stt_engine.transcribe(f)

        if any(PERSONA in phrase for phrase in transcribed):
            return (THRESHOLD, PERSONA)

        return (False, transcribed)


    def activeListen(self, persona, THRESHOLD=None, LISTEN=True, MUSIC=False):
        """
            Records until a second of silence or times out after 12 seconds
            Returns the first matching string or None
        """
        self._logger.info("#### Active Listen Start..... ##### ")
        self._logger.info("Ignoring %s", persona)
        self._logger.info("Play beep_hi.wav")
        self.speaker.play(jasperpath.data('audio', 'beep_hi.wav'))

        if self.active_stt_engine.has_mic() is True:
            
            self._logger.info("#### Active Listen stt engine has the mic..... ##### ")
            continueLoop = True
            while continueLoop:
                transcribed = self.active_stt_engine.transcribe(None)
                for text in transcribed:
                    self._logger.info("Transcribed : %s", text)
                    if text != persona:
                        continueLoop = False

        else:
            self._logger.info("#### Active Listen, jasper has the mic..... ##### ")
            transcribed = self.activeListenToAllOptions(THRESHOLD, LISTEN, MUSIC)

        self._logger.info("Play beep_lo.wav")
        self.speaker.play(jasperpath.data('audio', 'beep_lo.wav'))

        self._logger.info("#### Active Listen End..... ##### ")

        return transcribed


    def activeListenToAllOptions(self, THRESHOLD=None, LISTEN=True, MUSIC=False):
        """
            Records until a second of silence or times out after 12 seconds
            Returns a list of the matching options or None
        """
        # TODO: load a RATE from the profile. (bangor julius-cy needs 48000)
        RATE = 48000 # BangorSTT (Julius - 48000), BangorCloudSTT (Kaldi - 16000) 
        CHUNK = 1024
        LISTEN_TIME = 5 #12

        # check if no threshold provided
        if THRESHOLD is None:
            THRESHOLD = self.fetchThreshold()

        frames = []
        didDetect = False

        # prepare recording stream
        stream = self._audio.open(format=pyaudio.paInt16,
                                  channels=1,
                                  rate=RATE,
                                  input=True,
                                  frames_per_buffer=CHUNK)

        # detect when speaker starts speaking
        # start listening for disturbance above threshold
        for i in range(0, RATE / CHUNK * LISTEN_TIME):
            data = stream.read(CHUNK)
            frames.append(data)
            score = self.getScore(data)

            if score > THRESHOLD:
                didDetect = True
                break

        # no use continuing if no flag raised
        if not didDetect:
            stream.stop_stream()
            stream.close()
            self._logger.info("No disturbance detected")
            self.speaker.say("Sori nes i ddim clywed chi")
            return None

        # cutoff any recording before this disturbance was detected
        frames = frames[-20:]

        # increasing the range # results in longer pause after command
        # generation
        lastN = [THRESHOLD * 1.2 for i in range(30)]
        self._logger.info("Audio capture of range 0 to %s" % (RATE / CHUNK * LISTEN_TIME))

        for i in range(0, RATE / CHUNK * LISTEN_TIME):
            data = stream.read(CHUNK)
            frames.append(data)
            score = self.getScore(data)

            lastN.pop(0)
            lastN.append(score)

            average = sum(lastN) / float(len(lastN))

            # TODO: 0.8 should not be a MAGIC NUMBER!
            if average < THRESHOLD * 0.8:
                self._logger.info("Average %s less than 0.8 of threshold %s after i %s" % (average,THRESHOLD,i))
                break

        # save the audio data
        stream.stop_stream()
        stream.close()

        with tempfile.SpooledTemporaryFile(mode='w+b') as f:
            wav_fp = wave.open(f, 'wb')
            wav_fp.setnchannels(1)
            wav_fp.setsampwidth(pyaudio.get_sample_size(pyaudio.paInt16))
            wav_fp.setframerate(RATE)
            wav_fp.writeframes(''.join(frames))
            wav_fp.close()
            f.seek(0)
            return self.active_stt_engine.transcribe(f)


    def say(self, phrase,
            OPTIONS=" -vdefault+m3 -p 40 -s 160 --stdout > say.wav"):
        # alter phrase before speaking
        phrase = alteration.clean(phrase)
        self.speaker.say(phrase)
