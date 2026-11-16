/// <reference types="vite/client" />
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { PhoneApp } from './PhoneApp'
import { VoiceApp } from './voice/VoiceApp'
import { StageDemoApp } from './voice/StageDemoApp'
import { RoomView } from './RoomView'
import { DevPanel } from './dev/DevPanel'
import { devMode, hardwareMode } from './ws'

const classic = new URLSearchParams(location.search).has('classic')
const isRoom = location.pathname.replace(/\/$/, '').endsWith('/room')
const stage = !classic && hardwareMode && (
  new URLSearchParams(location.search).get('stage') === '1' || import.meta.env.VITE_STAGE_DEMO === '1'
)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {isRoom ? <RoomView /> : stage ? <StageDemoApp /> : classic ? <PhoneApp /> : <VoiceApp />}
    {devMode && <DevPanel />}
  </StrictMode>,
)
