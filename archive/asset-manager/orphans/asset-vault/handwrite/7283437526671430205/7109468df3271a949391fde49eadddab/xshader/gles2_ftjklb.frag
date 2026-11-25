precision highp float;
varying vec2 v_texcoord;
uniform sampler2D shapeTexture;
uniform vec3 colorRGB;
uniform float colorA;
void main(){
    vec4 simpleMask = texture2D(shapeTexture, v_texcoord);
    gl_FragColor = vec4(colorRGB, colorA * simpleMask.x);
}
