import assert from 'node:assert/strict'
import test from 'node:test'

import {
  disposeThreeRenderer,
  disposeThreeScene,
  viewerFailureMessage,
} from './viewerResources.js'

function disposable(extra = {}) {
  return { calls: 0, dispose() { this.calls += 1 }, ...extra }
}

test('disposeThreeScene releases shared geometry, materials, textures, and skeletons once', () => {
  const bitmap = { calls: 0, close() { this.calls += 1 } }
  const sharedTexture = disposable({ isTexture: true, source: { data: bitmap } })
  const uniformTexture = disposable({ isTexture: true })
  const background = disposable({ isTexture: true })
  const geometry = disposable()
  const material = disposable({
    map: sharedTexture,
    normalMap: sharedTexture,
    uniforms: { detail: { value: uniformTexture }, layers: { value: [sharedTexture, uniformTexture] } },
  })
  const skeleton = disposable()
  const objects = [
    { geometry, material, skeleton },
    { geometry, material: [material, material], skeleton },
  ]
  const scene = {
    background,
    environment: background,
    traverse(callback) { objects.forEach(callback) },
  }

  const counts = disposeThreeScene(scene)

  assert.deepEqual(counts, { geometries: 1, materials: 1, textures: 3, skeletons: 1 })
  assert.equal(geometry.calls, 1)
  assert.equal(material.calls, 1)
  assert.equal(sharedTexture.calls, 1)
  assert.equal(bitmap.calls, 1)
  assert.equal(uniformTexture.calls, 1)
  assert.equal(background.calls, 1)
  assert.equal(skeleton.calls, 1)
})

test('disposeThreeRenderer clears renderer caches and loses one context', () => {
  const calls = []
  const renderer = {
    domElement: { width: 1920, height: 1080 },
    setAnimationLoop(value) { calls.push(['loop', value]) },
    renderLists: { dispose() { calls.push(['lists']) } },
    dispose() { calls.push(['dispose']) },
    forceContextLoss() { calls.push(['context']) },
  }

  assert.equal(disposeThreeRenderer(renderer), true)
  assert.deepEqual(calls, [['loop', null], ['lists'], ['dispose'], ['context']])
  assert.deepEqual(renderer.domElement, { width: 1, height: 1 })
  assert.equal(disposeThreeRenderer(null), false)
})

test('viewerFailureMessage turns context creation failures into an actionable fallback', () => {
  const message = viewerFailureMessage(new Error('Error creating WebGL context.'))
  assert.match(message, /无法创建浏览器 3D 图形上下文/)
  assert.match(message, /静态渲染/)
  assert.match(message, /重试/)
  assert.match(viewerFailureMessage(new Error('HTTP 500')), /HTTP 500/)
})
